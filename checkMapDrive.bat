@echo off
set "DriveLetter=Z:"
set "SharePath=\\172.28.231.217\Alarm"
set "User=MiniPC"
set "Pass=LP123456"

:CheckServer
echo Checking connection to Server...
ping -n 1 172.28.231.217 | find "TTL=" >nul
if errorlevel 1 (
    echo Server is booting up or offline. Waiting 10 seconds...
    timeout /t 10 /nobreak >nul
    goto CheckServer
)

echo Server is online! Mapping Drive %DriveLetter%...
:: ลบ Drive Z: เก่าที่ค้างหรือขึ้นกากบาทแดงออกก่อน
net use %DriveLetter% /delete /y >nul 2>&1

:: สั่งต่อ Drive Z: ใหม่ด้วยบัญชีที่ถูกต้อง
net use %DriveLetter% "%SharePath%" /user:%User% %Pass% /persistent:yes

echo Drive %DriveLetter% is successfully mapped and ready!
exit


