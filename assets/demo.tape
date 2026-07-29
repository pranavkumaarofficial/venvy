# venvy demo — reproducible terminal GIF (charmbracelet/vhs).
# Render:  see assets/README.md   (one Docker command, no local vhs install)
#
# The demo environment and advisory database are baked into the render image
# (assets/demo/Dockerfile), so this tape has no setup: it just runs the scan.
# The env is built from metadata only, so nothing is installed and no code runs.

Output assets/demo.gif

Require venvy

Set Shell "bash"
Set FontSize 16
Set Width 1080
Set Height 460
Set Padding 20
Set Theme "Dracula"
Set TypingSpeed 55ms

Sleep 600ms
Type "venvy audit --env /demo/.venv"
Sleep 800ms
Enter
Sleep 5s
