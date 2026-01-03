# 清华大学校园卡洗浴分析器

- 上传校园卡交易记录，自动识别宿舍洗浴记录并生成三张分布图 + Markdown 年度报告。
- 懒人版请登录网站： https://thu-bath-report.onrender.com/ 
（render.com 免费托管，可能存在唤醒延迟，一般在1min内）

## 声明

- 灵感来源为： [THU-Canteen-Visualization-Annual-Report](https://github.com/19zbhy/THU-Canteen-Visualization-Annual-Report)，在此表示感谢。
- 本项目大部分代码使用 codex 完成。

## 功能概览

用户上传 Excel 格式的校园卡交易记录（获取方式同THU-Canteen-Visualization-Annual-Report），程序自动识别洗浴相关记录并生成分析报告。

- 自动识别时间、金额、商户列
- 支持选择 1 个或多个宿舍/公寓名称分析
- 规则：0:00-6:00 无热水不计入；10 分钟内合并；<=0.10 元小额自动吸附或剔除
- 输出：时段分布、开支分布、星期-小时热力图 + Markdown 报告

## 本地运行

```bash
python3 -m pip install -r requirements.txt
python3 app.py
```

访问 `http://127.0.0.1:5000` 上传 Excel。

