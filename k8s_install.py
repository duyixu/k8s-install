import os
import threading
hosts = {'master1':'192.168.1.200','node1':'192.168.1.201','node2':'192.168.1.202'}
k8s_versions = '1.15.2'
#安装相应依赖包
os.system('yum install ansible -y')

class myThread(threading.Thread):
   def __init__(self,name,Function):
       super().__init__()
       self.name = name
       self.Function = Function
   def run(self):
       print("开始线程："+ self.name)
       self.Function()
       print('退出线程：'+ self.name)

#将hosts IP写入相应文件中
def HostsFile():
    with open('/etc/hosts','a+',encoding='utf8') as file:
         for x,y  in hosts.items():
             result = f'{y}\t{x}\n'
             file.write(result)

#配置ansible hosts
def AnsibleHosts():
    os.system("sed -i '$ a \[master\]' /etc/ansible/hosts")
    os.system("sed -i '$ a \[nodes\]' /etc/ansible/hosts")
    for x,y  in hosts.items():
        if x[0] != 'm':
            os.system(f"sed -i '/^\[nodes\]/ a {y}' /etc/ansible/hosts")
        else:
            os.system(f"sed -i '/^\[master\]/ a {y}' /etc/ansible/hosts")

#配置kubernetes repo文件
def k8s_repo():
    k8s_repo = '''[kubernetes]
name=kubernetes
baseurl=https://mirrors.aliyun.com/kubernetes/yum/repos/kubernetes-el7-x86_64/
enable=1
gpgcheck=1
    '''
    with open('/etc/yum.repos.d/kubernetes.repo','w',encoding='utf8') as file:
            file.write(k8s_repo)

#
def SetNetwork():
    set_network='''net.bridge.bridge-nf-call-ip6tables = 1
net.bridge.bridge-nf-call-iptables = 1
vm.swappiness=0
    '''
    with open('/etc/sysctl.d/k8s.conf','w',encoding='utf8') as file:
        file.write(set_network)
try:
    thread1 = myThread('HostsFile',HostsFile)
    thread2 = myThread('AnsibleHosts',AnsibleHosts)
    thread3 = myThread('k8s_repo',k8s_repo)
    thread4 = myThread('SetNetwork',SetNetwork)
except Exception:
    print('线程创建失败！！！')
else:
    thread1.start()
    thread2.start()
    thread3.start()
    thread4.start()
    thread1.join()
    thread2.join()
    thread3.join()
    thread4.join()
    print('退出主线程！！！')

#实现所有节点免密登陆
os.system('ssh-keygen -t rsa -N ""  -f ~/.ssh/id_rsa')
for y in hosts.values():
  os.system(f'ssh-copy-id -i ~/.ssh/id_rsa.pub root@{y}')

#使用ansible对所有节点进行初始化
try:
 os.system('ansible-playbook ./nodes_initial.yml')
except Exception:
 print('k8s初始化失败！！！')
else:
#初始化k8s
 master_ip = hosts.get('master1')
 os.system('hostnamectl set-hostname master1')
 os.system(f'kubeadm init --apiserver-advertise-address={master_ip} \
 --image-repository registry.aliyuncs.com/google_containers  \
 --kubernetes-version={k8s_versions} --pod-network-cidr=10.244.0.0/16  --token-ttl=0  | tee ./k8s_install_log')
 #拷贝相应文件使其kubectl拥有操作k8s集群的权限
 os.system(' mkdir -p $HOME/.kube && cp -i /etc/kubernetes/admin.conf $HOME/.kube/config && chown $(id -u):$(id -g) $HOME/.kube/config')
 os.system("cat ./k8s_install_log  | egrep -i '(^kubeadm|--discovery).*' >> ./node_join.sh")
 os.system("ansible nodes -m copy -a 'src=./node_join.sh dest=~/'")
 os.system('ansible nodes -m shell -a "chmod +x ./node_join.sh && sh node_join.sh"')
 #初始化FlannelK8s集群网络
 os.system('kubectl apply -f https://raw.githubusercontent.com/coreos/flannel/master/Documentation/kube-flannel.yml')
