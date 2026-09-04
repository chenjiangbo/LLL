$removed=@()
function RemoveValueIfExists($key,$name,$match){
  if(Test-Path $key){
    $p=Get-ItemProperty -LiteralPath $key -ErrorAction SilentlyContinue
    $v=$p.$name
    if($null -ne $v -and (($null -eq $match) -or ([string]$v -match $match))){
      Remove-ItemProperty -LiteralPath $key -Name $name -Force -ErrorAction Stop
      $script:removed += "$key :: $name"
    }
  }
}
RemoveValueIfExists 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\FeatureUsage\AppSwitched' 'com.myquant.goldminer3.standard' $null
RemoveValueIfExists 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Search\JumplistData' 'com.myquant.goldminer3.standard' $null
RemoveValueIfExists 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\RunMRU' 'c' 'Essence Goldminer3|goldminer3|essence\.exe'
RemoveValueIfExists 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\TypedPaths' 'url1' 'Essence Goldminer3'
RemoveValueIfExists 'HKCU:\Software\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Compatibility Assistant\Store' 'C:\Users\chenjiangbo\AppData\Roaming\Essence Goldminer3\essence.exe' $null
RemoveValueIfExists 'HKCU:\Software\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Compatibility Assistant\Store' 'C:\Users\chenjiangbo\AppData\Roaming\Essence Goldminer3\uninst.exe' $null
RemoveValueIfExists 'HKCU:\Software\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Compatibility Assistant\Store' 'D:\QMT\installers\Essence-x64-3.24.1.5.exe' $null
$mui='HKCU:\Software\Classes\Local Settings\Software\Microsoft\Windows\Shell\MuiCache'
foreach($n in @(
'C:\Users\chenjiangbo\AppData\Roaming\Essence Goldminer3\essence.exe.FriendlyAppName',
'C:\Users\chenjiangbo\AppData\Roaming\Essence Goldminer3\essence.exe.ApplicationCompany',
'C:\Users\chenjiangbo\AppData\Roaming\Essence Goldminer3\resources\app\sms\strategy_manager.exe.FriendlyAppName',
'C:\Users\chenjiangbo\AppData\Roaming\Essence Goldminer3\resources\app\sms\strategy_manager.exe.ApplicationCompany',
'C:\Users\chenjiangbo\AppData\Roaming\Essence Goldminer3\resources\app\ds-proxy.exe.FriendlyAppName',
'C:\Users\chenjiangbo\AppData\Roaming\Essence Goldminer3\resources\app\gmterm-serv.exe.FriendlyAppName',
'D:\QMT\installers\Essence-x64-3.24.1.5.exe.FriendlyAppName',
'D:\QMT\installers\Essence-x64-3.24.1.5.exe.ApplicationCompany'
)){RemoveValueIfExists $mui $n $null}
foreach($k in @(
'HKCU:\Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\location\NonPackaged\C:#Users#chenjiangbo#AppData#Roaming#Essence Goldminer3#essence.exe',
'HKCU:\Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\location\NonPackaged\Executables\essence.exe'
)){if(Test-Path $k){Remove-Item -LiteralPath $k -Recurse -Force; $removed += $k}}
foreach($k in @(
'HKCU:\Software\Microsoft\Internet Explorer\LowRegistry\Audio\PolicyConfig\PropertyStore\308b6af4_0',
'HKCU:\Software\Microsoft\Internet Explorer\LowRegistry\Audio\PolicyConfig\PropertyStore\d4903cf6_0'
)){RemoveValueIfExists $k '(default)' 'Essence Goldminer3'}
$removed | ForEach-Object {Write-Output ('REMOVED '+$_)}
