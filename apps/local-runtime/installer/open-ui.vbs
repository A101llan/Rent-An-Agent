' "Open AgentHub Local": start the runtime if needed (hidden) and open http://127.0.0.1:8765/ui
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = dir
sh.Run """" & dir & "\agenthub-local-runtime.exe"" open", 0, False
