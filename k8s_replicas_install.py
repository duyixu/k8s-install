import os
import threading
domain = '192.168.1.11'
hosts = {'master1':'192.168.1.200',
         'master2':'192.168.1.201',
         'master3':'192.168.1.202',
         'node1':'192.168.1.10'}
CaFiles = ['/etc/kubernetes/pki/ca.crt',
'/etc/kubernetes/pki/ca.key',
'/etc/kubernetes/pki/sa.key',
'/etc/kubernetes/pki/sa.pub',
'/etc/kubernetes/pki/front-proxy-ca.crt',
'/etc/kubernetes/pki/front-proxy-ca.key',
'/etc/kubernetes/pki/etcd/ca.crt',
'/etc/kubernetes/pki/etcd/ca.key',
'/etc/kubernetes/admin.conf']
k8s_versions = '1.15.2'
#安装相应依赖包
os.system('yum install ansible -y')


class myThread(threading.Thread):
   def __init__(self,name,Function):
       super().__init__()
       self.name = name
       self.Function = Function
   def run(self):
        print(f'线程开始：{self.name}')
        self.Function()
        print(f'线程结束：{self.name}')


#将hosts IP写入相应文件中
with open('/etc/hosts','a+',encoding='utf8') as file:
     for x,y  in hosts.items():
         result = f'{y}\t{x}\n'
         file.write(result)

#配置ansible hosts
os.system("sed -i '$ a \[master\]' /etc/ansible/hosts")
os.system("sed -i '$ a \[nodes\]' /etc/ansible/hosts")
for x,y  in hosts.items():
    if x[0] != 'm':
        os.system(f"sed -i '/^\[nodes\]/ a {y}' /etc/ansible/hosts")
    else:
        os.system(f"sed -i '/^\[master\]/ a {y}' /etc/ansible/hosts")

#配置kubernetes repo文件
k8s_repo = '''[kubernetes]
name=kubernetes
baseurl=https://mirrors.aliyun.com/kubernetes/yum/repos/kubernetes-el7-x86_64/
enable=1
gpgcheck=1
'''
with open('/etc/yum.repos.d/kubernetes.repo','w',encoding='utf8') as file:
        file.write(k8s_repo)

#
set_network='''net.bridge.bridge-nf-call-ip6tables = 1
net.bridge.bridge-nf-call-iptables = 1
vm.swappiness=0
'''
with open('/etc/sysctl.d/k8s.conf','w',encoding='utf8') as file:
    file.write(set_network)

#实现所有节点免密登陆
os.system('ssh-keygen -t rsa -N ""  -f ~/.ssh/id_rsa')
for y in hosts.values():
  os.system(f'ssh-copy-id -i ~/.ssh/id_rsa.pub root@{y}')

os.system('ansible-playbook ./nodes_initial.yml --fork 10')

#将初始化配置写入文件
config = f'''apiVersion: kubeadm.k8s.io/v1beta1
kind: ClusterConfiguration
kubernetesVersion: {k8s_versions}
imageRepository: registry.aliyuncs.com/google_containers
apiServer:
  certSANs:
  - "{domain}"
controlPlaneEndpoint: "{domain}:6443"
networking:
   podSubnet: "10.244.0.0/16"
   dnsDomain: cluster.local
   serviceSubnet: "10.96.0.0/12"
'''
with open('./kubeadm-config.yaml','w',encoding='utf8') as file:
     file.write(config)

#使用配置文件初始化集群
os.system('kubeadm init --config ./kubeadm-config.yaml   | tee ./k8s_install_log ')

#将配置文件分发至其它master节点，提前下载相关镜像
def Dimages():
    for x,y in hosts.items():
        if x != 'master1' and  x[0] != 'n':
           os.system(f'ansible {y} -m copy -a "src=./kubeadm-config.yaml dest=/root"')
           os.system(f'ansible {y} -m shell -a "cd /root && kubeadm config images pull --config kubeadm-config.yaml"')

#将相关证书、配置文件等分发至其它master节点
def ConfigF():
    for  x,y in hosts.items():
         if x != 'master1' and x[0] != 'n':
             os.system(f"ssh root@{y} 'mkdir -p /etc/kubernetes/pki/etcd'")
             for value in CaFiles:
                 if value == '/etc/kubernetes/pki/etcd/ca.crt' or value == '/etc/kubernetes/pki/etcd/ca.key':
                     os.system(f'scp {value} root@{y}:/etc/kubernetes/pki/etcd/')
                 elif value == '/etc/kubernetes/admin.conf':
                     os.system(f'scp {value} root@{y}:/etc/kubernetes/')
                 else:
                     os.system(f'scp {value} root@{y}:/etc/kubernetes/pki/')
try:
    thread1 = myThread('Dimages',Dimages)
    thread2 = myThread('ConfigF',ConfigF)
except Exception:
    print('线程创建失败！！！')
else:
    thread1.start()
    thread2.start()
    thread1.join()
    thread2.join()
    print('主线程结束！！！')

def master_replicas():
    #将其它master节点加入master主节点
    os.system("cat k8s_install_log | egrep -i '(^  kubeadm|--discovery-token|--control)' | sed -n '1,3 p' >> ./master_join.sh")
    for x,y in hosts.items():
        if x != 'master1' and  x[0] != 'n':
            os.system(f"ansible {y} -m copy -a 'src=./master_join.sh dest=/root'")
            os.system(f"ansible {y} -m shell -a 'cd /root  && chmod +x ./master_join.sh && ./master_join.sh'" )

    #使其每个master节点可以通过kubectl操作k8s集群
    os.system('ansible master -m shell -a " mkdir -p $HOME/.kube &&  cp -i /etc/kubernetes/admin.conf $HOME/.kube/config && chown $(id -u):$(id -g) $HOME/.kube/config"')
    # 使用flannel初始化k8s集群网络
    os.system('kubectl apply -f https://raw.githubusercontent.com/coreos/flannel/master/Documentation/kube-flannel.yml')

def Nodes_join():
    #将node节点加入k8s集群
    os.system("cat ./k8s_install_log | egrep -i '(^kubeadm|--discovery).*' | sed -n '2,3 p' >> node_join.sh")
    os.system("ansible nodes -m copy -a 'src=./node_join.sh dest=/root'")
    os.system("ansible nodes -m shell -a 'cd /root && chmod +x node_join.sh && ./node_join.sh'")

try:
    thread3 = myThread('master_replicas',master_replicas)
    thread4 = myThread('Nodes_join',Nodes_join)
except Exception:
    print('线程创建失败！！！')
else:
    thread3.start()
    thread4.start()
    thread3.join()
    thread4.join()
    print('主线程结束')
