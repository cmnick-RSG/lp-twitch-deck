@echo off
REM Wrapper for Windows Task Scheduler -> runs the local daily collection via Git Bash.
REM Residential-IP replacement for the 403-blocked GitHub Actions pipeline.
"D:\Git\Git\usr\bin\bash.exe" -lc "'/d/AI Nikita/Traffic Dashboard Project Nikita/run_local_daily.sh'"
