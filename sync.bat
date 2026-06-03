@echo off
cd /d "%~dp0"
echo === Git 同步选股数据 ===
echo [1/3] 拉取远端...
git pull --no-rebase
echo [2/3] 添加本地结果...
git add data\results\
git diff --cached --quiet
if %errorlevel% neq 1 (
    echo   无新结果需要提交
) else (
    git commit -m "results: sync %date%"
)
echo [3/3] 推送到远端...
git push
echo === 同步完成 ===
pause
