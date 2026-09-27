# 默认审核手册入口

规则正文的唯一维护位置为 [包内 guidelines.md](src/ecoalign_forge/resources/guidelines.md)。

源码运行、wheel 安装和 sdist 构建均通过 `importlib.resources` 读取这一份正文；
当前工作目录中的同名文件不会覆盖规则。本入口不复制规则内容。

当前 Alpha 仅支持该默认手册定义的私域引流与低信息量内容领域。
通用规则包与运行时规则切换尚未实现。
