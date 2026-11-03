把模板图放到这个目录里。

推荐：
- 使用 png
- 尽量只截按钮本体，少带周围背景
- 文件名示例：start_button.png

在 script_action.py 中可直接这样用：

    bot.find_image("start_button")
    bot.click_image("start_button")
    bot.click_image_robust("start_button")

限定区域搜索示例：

    bot.find_image("start_button", search_rect=(402, 159, 717, 469))

当前挖宝图流程默认会用到这些模板（102BaoTuRenWu/）：

    bb_baotu.png
    jm_shiyong.png
    quxiao.png

当前秘境降妖流程默认会用到这些模板（107MiJingXiangyao/）：

    jm_mjxy.png
    jm_mjxy_tj.png
    jm_mjxy_yyl.png
    mjxy_jr.png
    mjxy_jxtz.png

另外复用 201ZhuaGui/quxiao.png 判断是否在战斗中。

当前抓鬼流程默认会用到这些模板（201ZhuaGui/）：

    jm_zgrw.png
    jm_jxzg_qd.png
    quxiao.png
