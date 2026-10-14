@echo off
setlocal
if defined JAVA_HOME (set "JAVA_EXE=%JAVA_HOME%\bin\java.exe") else (set "JAVA_EXE=java.exe")
"%JAVA_EXE%" -classpath "%~dp0gradle\wrapper\gradle-wrapper.jar" org.gradle.wrapper.GradleWrapperMain %*
