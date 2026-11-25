"""
build_bench.py — Generates out/bench_pen_vm.sb3 to benchmark Vanilla Scratch vs TurboWarp
CPU/List/Pen throughput and visually test PenSkin WebGL quirks.
"""

from pathlib import Path
from sb3_builder import ProjectBuilder, make_radial_glow_svg


def build_bench():
    pb = ProjectBuilder()
    s = pb.add_sprite("Bench")

    # Add optional radial glow costume for stamp vs pen comparison
    glow_svg, _ = make_radial_glow_svg(64)
    s.add_svg_costume("glow", glow_svg, rot_x=32, rot_y=32)

    # Result vars (ms)
    done = s.var("DONE", 0)
    t_math = s.var("MS_MATH_50K", 0)
    t_list = s.var("MS_LIST_50K", 0)
    t_pen_dot = s.var("MS_PEN_DOT_10K", 0)
    t_pen_scan = s.var("MS_PEN_SCAN_10K", 0)
    t_pen_span = s.var("MS_PEN_SPAN_1K", 0)
    t_pen_argb = s.var("MS_PEN_ARGB_5K", 0)
    t_stamp = s.var("MS_STAMP_2K", 0)

    # Scratch high-precision timer: days_since_2000 * 86400000 gives milliseconds with ~0.1ms precision!
    now_ms = lambda: s.mul(s.days_since_2000(), 86400000)

    t0 = s.var("t0", 0)
    i = s.var("i", 0)
    x = s.var("x", 0)
    y = s.var("y", 0)
    acc = s.var("acc", 0)
    col = s.var("col", 0)
    buf = s.lst("buf", [0] * 1000)

    # 1. Math benchmark (50k sqrt + dot)
    p_math = s.define_proc("bench_math", warp=True, body=[
        s.set_var("t0", now_ms()),
        s.set_var("acc", 0),
        s.set_var("i", 1),
        s.repeat(50000, [
            s.set_var("acc", s.add(acc, s.sqrt(s.add(s.mul(i, 0.001), 1.5)))),
            s.change_var("i", 1),
        ]),
        s.set_var("MS_MATH_50K", s.sub(now_ms(), t0)),
    ])

    # 2. List read/write benchmark (50k ops over 1000-elem list)
    p_list = s.define_proc("bench_list", warp=True, body=[
        s.set_var("t0", now_ms()),
        s.set_var("i", 1),
        s.repeat(50000, [
            s.replace_item(buf, s.add(s.mod(i, 1000), 1), s.add(s.item_of(buf, s.add(s.mod(i, 1000), 1)), 0.1)),
            s.change_var("i", 1),
        ]),
        s.set_var("MS_LIST_50K", s.sub(now_ms(), t0)),
    ])

    # 3. Pen point-by-point (100x100 = 10,000 dots)
    p_dot = s.define_proc("bench_pen_dot", warp=True, body=[
        s.pen_clear(),
        s.pen_set_size(1),
        s.set_var("t0", now_ms()),
        s.set_var("y", 0),
        s.repeat(100, [
            s.set_var("x", 0),
            s.repeat(100, [
                s.goto_xy(s.sub(x, 220), s.sub(160, y)),
                s.pen_set_color(s.add(s.mul(s.floor(s.mul(x, 2.5)), 65536), s.mul(s.floor(s.mul(y, 2.5)), 256))),
                s.pen_down(),
                s.pen_up(),
                s.change_var("x", 1),
            ]),
            s.change_var("y", 1),
        ]),
        s.set_var("MS_PEN_DOT_10K", s.sub(now_ms(), t0)),
    ])

    # 4. Pen continuous scanline (penDown once per row, 100x100 = 10,000 steps)
    p_scan = s.define_proc("bench_pen_scan", warp=True, body=[
        s.pen_set_size(1),
        s.set_var("t0", now_ms()),
        s.set_var("y", 0),
        s.repeat(100, [
            s.goto_xy(-100, s.sub(160, y)),
            s.pen_down(),
            s.set_var("x", 0),
            s.repeat(100, [
                s.pen_set_color(s.add(s.mul(s.floor(s.mul(x, 2.5)), 65536), s.mul(s.floor(s.mul(y, 2.5)), 256))),
                s.change_x(1),
                s.change_var("x", 1),
            ]),
            s.pen_up(),
            s.change_var("y", 1),
        ]),
        s.set_var("MS_PEN_SCAN_10K", s.sub(now_ms(), t0)),
    ])

    # 5. Pen horizontal RLE spans (100 rows x 10 spans = 1,000 spans covering 10,000 px)
    p_span = s.define_proc("bench_pen_span", warp=True, body=[
        s.pen_set_size(1),
        s.set_var("t0", now_ms()),
        s.set_var("y", 0),
        s.repeat(100, [
            s.set_var("x", 0),
            s.repeat(10, [
                s.pen_set_color(s.add(s.mul(s.floor(s.mul(x, 25)), 65536), s.mul(s.floor(s.mul(y, 2.5)), 256))),
                s.goto_xy(s.add(20, s.mul(x, 10)), s.sub(160, y)),
                s.pen_down(),
                s.change_x(9),
                s.pen_up(),
                s.change_var("x", 1),
            ]),
            s.change_var("y", 1),
        ]),
        s.set_var("MS_PEN_SPAN_1K", s.sub(now_ms(), t0)),
    ])

    # 6. Pen 32-bit ARGB translucent dots (5,000 calls)
    p_argb = s.define_proc("bench_pen_argb", warp=True, body=[
        s.pen_set_size(4),
        s.set_var("t0", now_ms()),
        s.set_var("i", 0),
        s.repeat(5000, [
            s.goto_xy(s.add(140, s.mod(i, 80)), s.sub(160, s.floor(s.div(i, 80)))),
            # 32-bit ARGB: alpha=32 -> 32*16777216 + R*65536 + G*256 + B
            s.pen_set_color(32 * 16777216 + 255 * 65536 + 140 * 256 + 40),
            s.pen_down(),
            s.pen_up(),
            s.change_var("i", 1),
        ]),
        s.set_var("MS_PEN_ARGB_5K", s.sub(now_ms(), t0)),
    ])

    # 7. Pen Stamp benchmark (2,000 stamps of radial glow sprite)
    p_stamp = s.define_proc("bench_stamp", warp=True, body=[
        s.switch_costume("glow"),
        s.set_size(50),
        s.set_effect("GHOST", 85),
        s.set_var("t0", now_ms()),
        s.set_var("i", 0),
        s.repeat(2000, [
            s.goto_xy(s.add(-200, s.mod(i, 120)), s.sub(-30, s.floor(s.div(i, 20)))),
            s.pen_stamp(),
            s.change_var("i", 1),
        ]),
        s.switch_costume("blank"),
        s.set_effect("GHOST", 0),
        s.set_var("MS_STAMP_2K", s.sub(now_ms(), t0)),
    ])

    # 8. Visual Physics Verification Panel (draw clean diagnostic quadrants!)
    p_visual = s.define_proc("draw_visual_diag", warp=True, body=[
        s.pen_clear(),
        # Dark background
        s.pen_set_color(0x0D1117),
        s.pen_set_size(400),
        s.goto_xy(-240, 0), s.pen_down(), s.goto_xy(240, 0), s.pen_up(),

        # Q1 (Top-Left): size=2 dot grid (shows corner pinholes!)
        s.pen_set_size(2),
        s.set_var("y", 0),
        s.repeat(60, [
            s.set_var("x", 0),
            s.repeat(90, [
                s.goto_xy(s.add(-220, s.mul(x, 2)), s.sub(160, s.mul(y, 2))),
                s.pen_set_color(s.add(s.mul(s.floor(s.mul(x, 2.8)), 65536), s.add(s.mul(s.floor(s.mul(y, 4)), 256), 180))),
                s.pen_down(),
                s.pen_up(),
                s.change_var("x", 1),
            ]),
            s.change_var("y", 1),
        ]),

        # Q2 (Top-Right): size=2 horizontal 1px segment (ZERO pinholes!)
        s.pen_set_size(2),
        s.set_var("y", 0),
        s.repeat(60, [
            s.set_var("x", 0),
            s.repeat(90, [
                s.goto_xy(s.add(20, s.mul(x, 2)), s.sub(160, s.mul(y, 2))),
                s.pen_set_color(s.add(s.mul(s.floor(s.mul(x, 2.8)), 65536), s.add(s.mul(s.floor(s.mul(y, 4)), 256), 180))),
                s.pen_down(),
                s.change_x(1),
                s.pen_up(),
                s.change_var("x", 1),
            ]),
            s.change_var("y", 1),
        ]),

        # Q3 (Bottom-Left): Continuous pen-down scanline checkerboard (tests cap bleed!)
        s.pen_set_size(4),
        s.set_var("y", 0),
        s.repeat(24, [
            s.goto_xy(-220, s.sub(-20, s.mul(y, 4))),
            s.pen_down(),
            s.set_var("x", 0),
            s.repeat(44, [
                s.if_else(
                    s.eq(s.mod(s.add(x, y), 2), 0),
                    [s.pen_set_color(0xFFCC44)],
                    [s.pen_set_color(0x2244AA)],
                ),
                s.change_x(4),
                s.change_var("x", 1),
            ]),
            s.pen_up(),
            s.change_var("y", 1),
        ]),

        # Q4 (Bottom-Right): Pure Pen 32-bit ARGB Multi-Layer GPU Bloom Test!
        # Concentric glowing plasma orb rendered with layered translucent Pen dots
        s.set_var("i", 0),
        s.repeat(18, [
            # size from 130 down to 12, alpha from 5 up to 40
            s.pen_set_size(s.sub(130, s.mul(i, 6.5))),
            s.pen_set_color(s.add(
                s.mul(s.floor(s.add(5, s.mul(i, 1.4))), 16777216),
                s.add(255 * 65536, s.add(s.mul(s.floor(s.add(80, s.mul(i, 9))), 256), s.floor(s.add(20, s.mul(i, 12)))))
            )),
            s.goto_xy(110, -80),
            s.pen_down(),
            s.pen_up(),
            s.change_var("i", 1),
        ]),
        # Hot white core
        s.pen_set_size(14),
        s.pen_set_color(0xFFFFFF),
        s.goto_xy(110, -80),
        s.pen_down(),
        s.pen_up(),
    ])

    s.when_flag_clicked([
        s.hide(),
        s.call_proc(p_math),
        s.call_proc(p_list),
        s.call_proc(p_dot),
        s.call_proc(p_scan),
        s.call_proc(p_span),
        s.call_proc(p_argb),
        s.call_proc(p_stamp),
        s.call_proc(p_visual),
        s.set_var("DONE", 1),
    ])

    out = pb.save_sb3(Path(__file__).resolve().parent / "sb3" / "bench_pen_vm.sb3")
    print("Built:", out)


if __name__ == "__main__":
    build_bench()
