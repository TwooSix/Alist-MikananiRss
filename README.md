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
1. 参考[官方文档](https://rye-up.com/guide/installation/)安装Rye 
   - linux:
   ```shell
   curl -sSf https://rye-up.com/get | bash
   ```
   - windows: [rye-x86_64-windows.exe](https://github.com/astral-sh/rye/releases/latest/download/rye-x86_64-windows.exe) for 64bit Intel Windows
2. 下载源码
   ```shell
   git clone https://github.com/TwooSix/Alist-MikananiRss.git && cd Alist-MikananiRss
   ```
3. 初始化运行环境
   ```shell
   rye sync
   ```
3. 在目录下新建一个`config.yaml`配置文件，并填写配置文件如下(完整功能示例详解见`example_full.yaml`)
   ```yaml
   common:
     interval_time: 300
   
   alist:
     base_url: https://example.com # 修改为你的alist访问地址
     token: alist-xxx # 修改为你的alist token；可在"管理员后台->设置->其他"中找到
     downloader: qBittorrent # 或者 aria2
     download_path: Onedrive/Anime # 修改为你的下载路径，相对于alist根目录
   
   mikan:
     subscribe_url: https://mikanani.me/RSS/MyBangumi?token=xxx # 修改为你的蜜柑订阅地址
   
   filters:
    - 1080p
    - 非合集
   
   rename:
     regex: ~
   ```
4. 运行代码：`rye run alist-mikananirss`  

5. Enjoy

## 重命名效果展示
<div align=center>
<img src="https://github.com/TwooSix/Alist-MikananiRss/blob/master/imgs/show_pic1.png"/>
</div>
