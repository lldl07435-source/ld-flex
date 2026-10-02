# 外部依赖与参考

| 项目 | 用途 | 许可 / 来源 |
|---|---|---|
| Python | 本地服务、实验和工具 | Python Software Foundation License |
| pyserial 3.5 | 可选串口通信 | BSD 3-Clause；https://github.com/pyserial/pyserial |
| GCC / Arm GNU Toolchain | 编译 C 控制核心和固件 | 各工具自身许可；本仓库不重新分发编译器 |
| STM32 RM0008 | 引脚外设、定时器、串口与看门狗接口依据 | ST 官方手册，链接见选题与边界 |

前端使用原生 HTML、CSS、JavaScript，没有外部字体、图标包或 CDN。SVG 结构图与界面图形随本工程提供。调度实现使用经典 FIFO、EDD、贪心与束搜索思路；不把这些方法名称作为本项目的新算法主张。
