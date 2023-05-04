<h1 align="center">
  Alist-MikananiRss
</h1>
<p align="center">
  从<a href="https://mikanani.me/">蜜柑计划</a>的RSS订阅源中自动获取番剧更新并通过Alist离线下载至对应网盘
</p>  

## 准备工作 
1. 请自行参照[Alist](https://github.com/alist-org/alist)项目文档部署Alist，并搭建好Aria2离线下载
2. 自行注册蜜柑计划账户，订阅番剧，获取订阅链接

## 如何使用
1. 下载源码
```shell
git clone https://github.com/TwooSix/Alist-MikananiRss.git && cd Alist-MikananiRss
```
2. 安装依赖(Python>=3.9)
```shell
pip install -r requirements.txt
```
3. 在目录下新建一个`config.py`配置文件，并填写配置文件，具体填写示例见`example.py`
	 - `DOMAIN`：字符串，你的alist部署域名，如`www.example.com`
	 - `USER_NAME`, `PASSWORD`：字符串，你的Alist账户密码
	 - `DOWNLOAD_PATH`：字符串，你的下载文件夹，从登陆用户的根目录开始，如`AliyunPan/Anime`
	 - `REGEX_PATTERN`：字典，你的正则表达式规则，填写方式为`{name: regex}`（当然也可以复制用我写的），如`{"1080": r"(1080[pP])}"`
	 - `SUBSCRIBE_URL`: 字符串，你的RSS订阅链接
	 - `FILTERS`: 列表，使用的正则表达式规则，填写名字即可，如`["1080"]`
	 - `INTERVAL_TIME`: 整数，执行的间隔时间
4. 运行代码：`python main.py`  
  (后台执行则为：`nohup python main.py > /dev/null 2>&1 &`)
5. Enjoy

## 开启订阅更新通知（可选）
### Telegram 通知
在`config.py`中加入以下配置
```python
TELEGRAM_NOTIFICATION = True # 开启Telegram通知，为 False 则关闭
BOT_TOKEN = "你的 BOT_TOKEN"
USER_ID = "你的 USER_ID"
```

