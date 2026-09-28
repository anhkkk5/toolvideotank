@echo off
chcp 65001 > nul
title TankVideo Studio - Cap nhat tu dong
color 0E

echo ========================================
echo   TANKVIDEO STUDIO - CAP NHAT TU DONG
echo ========================================
echo.

:: Tim thu muc TankVideo (tim TankVideo.exe)
set "TANK_DIR="

:: Uu tien: cung thu muc voi script
if exist "%~dp0TankVideo.exe" (
    set "TANK_DIR=%~dp0"
    goto found
)

:: Tim tren Desktop
for %%d in ("%USERPROFILE%\Desktop" "%USERPROFILE%\OneDrive\Desktop" "%PUBLIC%\Desktop") do (
    if exist "%%~d\TankVideo\TankVideo.exe" (
        set "TANK_DIR=%%~d\TankVideo\"
        goto found
    )
)

:: Tim o D:\, E:\, C:\
for %%d in (D E C F G) do (
    if exist "%%d:\TankVideo\TankVideo.exe" (
        set "TANK_DIR=%%d:\TankVideo\"
        goto found
    )
    if exist "%%d:\TankVideo\TankVideo\TankVideo.exe" (
        set "TANK_DIR=%%d:\TankVideo\TankVideo\"
        goto found
    )
)

:: Khong tim thay -> hoi nguoi dung
echo [!] Khong tim thay thu muc TankVideo tu dong.
echo     Vui long keo file nay vao thu muc TankVideo roi chay lai.
echo.
pause
exit /b 1

:found
echo [OK] Tim thay TankVideo tai: %TANK_DIR%
echo.

:: 1. Tat TankVideo.exe neu dang chay
echo [1/5] Dang tat TankVideo.exe...
taskkill /f /im TankVideo.exe >nul 2>&1
ping 127.0.0.1 -n 3 > nul

:: 2. Tai patch.zip tu Google Drive (xu ly confirm cho file lon)
echo [2/5] Dang tai ban cap nhat (~74 MB), vui long cho...
set "FILE_ID=1r-asAt_CN35hidm8i1f1xqM-Rn9vBe6S"
set "TEMP_ZIP=%TANK_DIR%temp_update.zip"

:: Xoa file cu neu co
if exist "%TEMP_ZIP%" del /f /q "%TEMP_ZIP%" >nul 2>&1

:: Dung PowerShell voi Invoke-WebRequest de xu ly Google Drive confirm page
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference = 'Stop'; " ^
  "$fileId = '%FILE_ID%'; " ^
  "$out = '%TEMP_ZIP%'; " ^
  "$baseUrl = 'https://drive.google.com/uc?export=download&id=' + $fileId; " ^
  "try { " ^
  "  Write-Host 'Ket noi Google Drive...'; " ^
  "  $session = New-Object Microsoft.PowerShell.Commands.WebRequestSession; " ^
  "  $resp = Invoke-WebRequest -Uri $baseUrl -SessionVariable session -UseBasicParsing -MaximumRedirection 5; " ^
  "  $contentType = $resp.Headers['Content-Type']; " ^
  "  if ($contentType -and $contentType.ToString().Contains('text/html')) { " ^
  "    Write-Host 'File lon, can xac nhan...'; " ^
  "    $confirmUrl = $baseUrl + '&confirm=t'; " ^
  "    Invoke-WebRequest -Uri $confirmUrl -WebSession $session -OutFile $out -UseBasicParsing; " ^
  "  } else { " ^
  "    [System.IO.File]::WriteAllBytes($out, $resp.Content); " ^
  "  }; " ^
  "  $size = (Get-Item $out).Length; " ^
  "  $sizeMB = [math]::Round($size / 1MB, 1); " ^
  "  Write-Host ('Da tai xong: ' + $sizeMB + ' MB'); " ^
  "  if ($size -lt 1048576) { " ^
  "    Write-Host 'File qua nho, co the loi. Thu phuong phap 2...'; " ^
  "    $url2 = 'https://drive.usercontent.google.com/download?id=' + $fileId + '&export=download&confirm=t'; " ^
  "    Invoke-WebRequest -Uri $url2 -OutFile $out -UseBasicParsing; " ^
  "    $size2 = (Get-Item $out).Length; " ^
  "    Write-Host ('Phuong phap 2: ' + [math]::Round($size2 / 1MB, 1) + ' MB'); " ^
  "  }; " ^
  "} catch { " ^
  "  Write-Host ('LOI: ' + $_.Exception.Message); " ^
  "  exit 1; " ^
  "}"

if not exist "%TEMP_ZIP%" (
    echo [LOI] Khong the tai file cap nhat!
    pause
    exit /b 1
)

:: Kiem tra file size (phai > 1MB)
for %%A in ("%TEMP_ZIP%") do (
    if %%~zA LSS 1048576 (
        echo [LOI] File tai ve qua nho %%~zA bytes, co the bi loi!
        echo      Thu tai thu cong: https://drive.google.com/file/d/%FILE_ID%/view
        del /f /q "%TEMP_ZIP%" >nul 2>&1
        pause
        exit /b 1
    )
)

:: 3. Doi ten file cu
echo [3/5] Doi ten file cu...
set "TARGET_EXE=%TANK_DIR%TankVideo.exe"
set "TARGET_OLD=%TANK_DIR%TankVideo.exe.old"

if exist "%TARGET_OLD%" del /f /q "%TARGET_OLD%" >nul 2>&1
if exist "%TARGET_EXE%" (
    move /y "%TARGET_EXE%" "%TARGET_OLD%" >nul 2>&1
    if exist "%TARGET_EXE%" (
        echo [LOI] Khong the doi ten file cu. Co the TankVideo van dang chay.
        echo       Hay dong tat ca cua so TankVideo roi chay lai script nay.
        pause
        exit /b 1
    )
)

:: 4. Giai nen bang PowerShell
echo [4/5] Dang giai nen ban cap nhat...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "try { Expand-Archive -Path '%TEMP_ZIP%' -DestinationPath '%TANK_DIR%' -Force; Write-Host 'OK' } catch { Write-Host $_.Exception.Message; exit 1 }"

:: Kiem tra
if not exist "%TARGET_EXE%" (
    echo [!] Thu phuong phap giai nen 2...
    tar -xf "%TEMP_ZIP%" -C "%TANK_DIR%" >nul 2>&1
)

if not exist "%TARGET_EXE%" (
    echo [LOI] Khong the giai nen file cap nhat!
    if exist "%TARGET_OLD%" move /y "%TARGET_OLD%" "%TARGET_EXE%" >nul 2>&1
    pause
    exit /b 1
)

:: 5. Don dep
echo [5/5] Don dep va khoi dong lai...
if exist "%TEMP_ZIP%" del /f /q "%TEMP_ZIP%" >nul 2>&1
if exist "%TARGET_OLD%" del /f /q "%TARGET_OLD%" >nul 2>&1

echo.
echo ========================================
echo   CAP NHAT THANH CONG!
echo   Dang khoi dong lai TankVideo Studio...
echo ========================================
echo.
ping 127.0.0.1 -n 2 > nul
start /d "%TANK_DIR%" "" "%TARGET_EXE%"
exit
