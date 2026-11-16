# Skill Controller

这是可配置的键鼠技能循环程序第一版，界面使用 PySide6-Fluent-Widgets（QFluentWidgets）。

## macOS 开发运行

```bash
cd /Users/xipilabs/dev/Experiment/LLL
python3 -m pip install -r requirements-skill-controller.txt
python3 scripts/skill_controller_gui.py
```

macOS 首次运行需要在“系统设置 → 隐私与安全性 → 辅助功能”中允许运行 Python 的终端程序接收输入事件。

## Windows 运行

```powershell
py -m pip install -r requirements-skill-controller.txt
py scripts\skill_controller_gui.py
```

后续可以使用 PyInstaller 打包：

```powershell
py -m pip install pyinstaller
pyinstaller --noconsole --name SkillController scripts\skill_controller_gui.py
```

配置保存位置：

```text
Windows: %APPDATA%\SkillController\profiles.json
macOS:   ~/.config/SkillController/profiles.json
```

## 当前支持

- 新建、删除技能
- 技能触发键
- 按一下切换、按住运行、执行一次
- 独立循环动作
- 顺序动作组
- 按键点按、按住、松开
- 鼠标左键、右键、中键
- 首次延迟、循环间隔、动作后等待
- 总开关和技能切换等待
- 双击已有动作进行编辑
