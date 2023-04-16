# Alist-MikananiRss
## 如何使用
1. 下载源码
```shell
git clone https://github.com/TwooSix/Alist-MikananiRss.git
```
2. 安装依赖
```shell
cd Alist-MikananiRss && pip install -r requirements.txt
```
3. 在`Config.py`文件编写配置文件
	 - 在`domain`字段填写你的alist部署域名，示例`www.example.com`
	 - 在`username`, `password`字段填写你的Alist账户密码
	 - 在`downloadPath`字段填写你的下载文件夹，示例`AliyunPan/Anime`
	 - 在`rss`字段填写你的RSS订阅
		- `url`：你从蜜柑计划获取的RSS链接
		- `filter`：通过正则表达式过滤结果，目前我只个人内置了'简体'，'繁体'，'1080'，'非合集'四种，写的也比较粗糙
		- `subfolder`：子文件夹名，决定是否单独存放到子文件夹，不填则默认下载到`downloadPath`，填写则下载到`downloadPath/subfoler`  
填写示例见`ConfigExample.py`
1. 运行代码`python main.py`
2. Enjoy
## 自定义正则表达式
方法1：
在`main.py`文件里修改，示例：
```python
import Filter
Filter.addFilter('720', r'(720[pP])')
```
`addFilter(name, regex)`
- name: 你的规则名字
- regex：你的正则表达式

方法2：
直接到`Filter.py`文件里修改`Filter`字典

添加完成后，就可以在创建`RSS`类时的`filter`字段列表里，加入你自定义规则的`name`来使用你自己的正则表达式了。
如刚才例子中添加了720p的规则，则可以在配置文件里直接这样使用：
```python
{
	'url': 'https://xxx',
	'filter': ['720'],
}
```
当然，你也可以用同名的方法，覆盖掉我随便写的正则表达式