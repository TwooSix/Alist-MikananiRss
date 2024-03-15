<h1 align="center">
  Alist-MikananiRss
</h1>
<p align="center">
  从<a href="https://mikanani.me/">蜜柑计划</a>的RSS订阅源中自动获取番剧更新并通过Alist离线下载至对应网盘
</p>  
<p align="center">
  并结合使用ChatGPT分析资源名，将资源重命名为Emby可解析的格式。
</p>  

## 功能
- 自动获取番剧更新并下载至对应网盘
- telegram更新通知
- 自动重命名为emby可识别格式

## 准备工作 
1. 请自行参照[Alist](https://github.com/alist-org/alist)项目文档部署Alist（版本须>=3.29.0），并搭建好Aria2/qBittorrent离线下载
2. 自行注册蜜柑计划账户，订阅番剧，获取订阅链接

## 如何使用
1. 下载源码
```shell
git clone https://github.com/TwooSix/Alist-MikananiRss.git && cd Alist-MikananiRss
```
2. 安装依赖(Python==3.11)
```shell
pip install -r requirements.txt
```
1. 在目录下新建一个`config.yaml`配置文件，并填写配置文件，简单示例见`example.yaml`，完整功能示例见`example_full.yaml`

2. 运行代码：`python main.py`  

3. Enjoy

## 重命名效果展示
<div align=center>
<img src="https://github.com/TwooSix/Alist-MikananiRss/blob/master/imgs/show_pic1.png"/>
</div>
