# GitHub 开源步骤

本地仓库已建立；尚未创建或推送远端。`data/`、`evidence/`、`.venv/` 和编译产物由 `.gitignore` 排除，原始记录仍保留在电脑里。

## 上传前检查

1. 关闭工作台，运行 `一键验收.cmd`，确认最后的 `all_passed` 为 true。
2. 运行 `git status --short`，检查是否只有你准备公开的源码、文档、示例。
3. 打开准备公开的 CSV、图片和日志，删除公开副本中的私人信息；保留本机原件。不要提交身份证、申请表或系统密钥。
4. 阅读 MIT 许可证，确认采用这个许可开放代码；引用第三方材料时保留相应许可和来源。
5. 登录 GitHub 新建空仓库，例如 `ld-flex-cell`，先不要在网页上自动生成 README 或许可证。

## 推送

在 PyCharm Terminal 中执行，把示例地址改成你自己的真实仓库：

```powershell
git remote add origin https://github.com/你的用户名/ld-flex-cell.git
git push -u origin codex/ld-flex
```

到 GitHub 仓库设置里确认默认分支；也可以另建 main 后通过 Pull Request 合并。已有远端时先 `git remote -v` 核对，不覆盖别的项目地址。

提交身份此前已按你的要求配置为“距离 / 3043458602@qq.com”。邮箱会出现在提交元数据中。如果以后希望改用 GitHub 提供的 noreply 邮箱，在下一次提交前设置本仓库的 user.email；不要为美化日期重写已有历史。

## 发布内容

README、源码、测试、工作台、接线、结构尺寸、实验协议和当前验收摘要。`.github/workflows/verify.yml` 在推送后运行 Linux 上的两种 Python 版本测试；目前配置已经写入，远端执行结果要到实际推送后确认。

发布页可以另附经过校验的 `ld-flex.bin`、Windows 控制库和独立说明书。公开硬件照片、视频及真实测量曲线后，项目的可信度会比只放代码更完整。不要提前写尚未取得的奖项、量产能力或工业安全认证。
