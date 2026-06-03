# 自动化选股系统

## 环境准备

```bash
pip install -r requirements.txt
```

## 配置微信推送

1. 打开 https://www.pushplus.plus/ 注册
2. 复制你的 Token
3. 设置环境变量：

```powershell
# Windows PowerShell
[System.Environment]::SetEnvironmentVariable('PUSHPLUS_TOKEN', '你的token', 'User')
```

或每次运行前：
```bash
export PUSHPLUS_TOKEN=你的token
```

## 每日使用

```bash
# 收盘后运行（默认用今天日期）
python run.py

# 指定日期（复盘历史）
python run.py 20260601
```

## 查看复盘

```bash
python app.py
# 浏览器打开 http://127.0.0.1:5000
```

## 两台电脑同步

### 首次配置

```bash
# 在 GitHub/Gitee 创建一个私有仓库，例如 my-stock-screener
git remote add origin <你的仓库地址>
git push -u origin main
```

### 另一台电脑

```bash
git clone <你的仓库地址>
pip install -r requirements.txt
# 同样设置 PUSHPLUS_TOKEN
```

### 日常同步

`run.py` 会自动 pull + push。如需手动同步：
- Windows: 双击 `sync.bat`
- Git Bash: `bash sync.sh`

## Windows 定时运行

1. 打开"任务计划程序"
2. 创建任务 → 触发器：每天 15:30
3. 操作：启动程序 `python`，参数 `F:\AI\STOCK\run.py`
