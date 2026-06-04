# CLAUDE.md — 自动化选股系统

## 项目概述

A股自动化选股系统：每日收盘后筛选次日观察池，微信推送 + 本地 Web 复盘。

## 选股模型

| 步骤 | 条件 |
|---|---|
| 池子 | 创业板 + 科创板 + 北交所 |
| 排除 | ST、*ST、上市<100天 |
| 市值 | < 400亿 |
| 初筛 | 5日/10日/单日涨幅各自Top30，去重 |
| 量价形态 | 10-15日内先放量涨→后缩量调（模糊判定） |
| 输出 | 每日观察池 → 微信推送 |

## 技术栈

- Python 3.9+, Flask, pandas, akshare, requests
- 数据源：新浪（股票列表+K线），腾讯（市值）
- 推送：PushPlus → 微信
- 同步：Git（只同步 data/results/，不同步 data/cache/）

## 用户偏好

- 不使用 akshare 的东方财富数据源（被封），使用新浪+腾讯
- 先模糊实现量价形态，后续根据效果微调
- 微信推送暂不配置，先用本地 Web 页面看结果
- 两台电脑（单位+家里），Git 同步筛选结果

## 关键文件

- `run.py` / `run.bat` — 每日一键选股
- `app.py` — Web 复盘页面 (http://127.0.0.1:5000)
- `engine/fetcher.py` — 数据获取（新浪+腾讯）
- `engine/conditions.py` — 选股条件
- `engine/screener.py` — 筛选引擎
- `pull.bat` — 同步远端结果
- `data/results/` — 筛选结果 CSV（Git 同步）
- `data/cache/` — K线缓存（不同步）
