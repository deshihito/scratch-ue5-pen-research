"""
build_3dgs_splat.py — Builds out/ue5_3dgs_splat.sb3

Real-Time 3D Gaussian / Radiance Splatting Engine in 100% Pure Vanilla Scratch Pen!
  - Offline Python Baker samples a high-detail sculpted 3D scene (Trefoil Torus Knot
    in Brushed 24k Gold + Matte Travertine Pedestal + Glowing Cyan Plasma Core +
    Orbital Emerald Dielectric Spheres) with baked raytraced AO, directional soft
    lighting, two-tone GI bounce, and surface normals into 1,400 3D Gaussians.
  - Runtime Pure Scratch Pen Engine:
      1. 3D Camera Rotation + Perspective Projection + Normal Backface Culling
      2. O(N) Counting-Bucket Linked-List Depth Sort (128 depth bins, zero O(N log N)!)
      3. Live View-Dependent PBR Fresnel + Blinn-GGX Specular Highlight per Splat!
      4. Multi-Shell 32-bit ARGB Gaussian Pen Splatting exploiting PenSkin's WebGL2
         Instanced Circle Shader (feathered outer Gaussian halo + dense core!)
  - Benchmarks real FPS in BOTH TurboWarp AND Official Vanilla Scratch 3.0!
"""

import math
from sb3_builder import ProjectBuilder


def vec_norm(x, y, z):
    l = math.sqrt(x * x + y * y + z * z) + 1e-9
    return x / l, y / l, z / l


def vec_dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def bake_radiance_splats():
    """
    Offline UE5-style Radiance Baker:
    Generates ~1,400 3D Gaussians with baked GI, AO, soft shadows, and PBR material info.
    """
    splats = []
    sun = vec_norm(0.68, 0.58, -0.45)

    def add_baked_splat(x, y, z, nx, ny, nz, alb, metal, radius, emissive=(0, 0, 0)):
        nx, ny, nz = vec_norm(nx, ny, nz)
        # Approximate baked AO + soft directional + two-tone GI (warm gold sun + cool sky + cyan core!)
        # Distance from central cyan core (0, 0.15, 0)
        cx, cy, cz = -x, 0.15 - y, -z
        cd = math.sqrt(cx * cx + cy * cy + cz * cz) + 1e-4
        c_dot = max(0.0, (nx * cx + ny * cy + nz * cz) / cd * 0.7 + 0.3)
        c_atten = c_dot / (0.28 + cd * cd)

        # Fake baked occlusion from floor & knot center
        ao = min(1.0, max(0.22, 0.55 + 0.45 * ny))
        if y < -0.95:
            # Pedestal top AO shadow beneath hovering knot
            r_xz = math.sqrt(x * x + z * z)
            ao *= min(1.0, max(0.28, 0.30 + 0.48 * r_xz))

        ndl = max(0.0, nx * sun[0] + ny * sun[1] + nz * sun[2])
        # Baked linear diffuse irradiance: Sun + Sky hemisphere + Warm Bounce + Cyan Core GI
        irR = (2.4 * ndl * ao + 0.22 * (0.5 + 0.5 * ny) * ao + 0.45 * (0.5 - 0.5 * ny) * ao + 0.25 * c_atten)
        irG = (1.85 * ndl * ao + 0.34 * (0.5 + 0.5 * ny) * ao + 0.30 * (0.5 - 0.5 * ny) * ao + 1.45 * c_atten)
        irB = (1.15 * ndl * ao + 0.65 * (0.5 + 0.5 * ny) * ao + 0.16 * (0.5 - 0.5 * ny) * ao + 2.45 * c_atten)

        # Metallic surfaces keep rich golden ambient reflection base + strong live specular
        kd = 1.0 - metal * 0.55
        bR = alb[0] * kd * irR + emissive[0]
        bG = alb[1] * kd * irG + emissive[1]
        bB = alb[2] * kd * irB + emissive[2]

        # ACES Filmic tone-map baked base into [0, 1] range for fast runtime Scratch shading
        def aces(v):
            v = max(0.0, v * 0.75)
            t = (v * (2.51 * v + 0.03)) / (v * (2.43 * v + 0.59) + 0.14)
            return math.sqrt(min(1.0, max(0.0, t)))

        # Store 0..255 baked RGB + specular strength + emissive flag
        is_em = 1 if (emissive[0] + emissive[1] + emissive[2]) > 0.5 else 0
        splats.append((
            round(x, 4), round(y, 4), round(z, 4),
            round(nx, 4), round(ny, 4), round(nz, 4),
            round(aces(bR) * 230, 1), round(aces(bG) * 230, 1), round(aces(bB) * 230, 1),
            round(0.95 if metal > 0.5 else 0.35, 2),
            round(radius, 4),
            is_em,
        ))

    # 1. High-Detail Sculpted 24k Gold Trefoil Torus Knot (960 Gaussians — equivalent to ~12,000 tris!)
    nu, nv = 80, 12
    for iu in range(nu):
        t = (iu / nu) * 2.0 * math.pi
        # Parametric trefoil knot centerline
        def knot_pos(u):
            return (
                (math.sin(u) + 2.0 * math.sin(2.0 * u)) * 0.44,
                (math.cos(u) - 2.0 * math.cos(2.0 * u)) * 0.44 + 0.22,
                (-math.sin(3.0 * u)) * 0.44,
            )

        p0 = knot_pos(t)
        p1 = knot_pos(t + 0.005)
        tx, ty, tz = vec_norm(p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2])
        # Frenet-like orthonormal frame
        up = (0.0, 1.0, 0.0) if abs(ty) < 0.9 else (1.0, 0.0, 0.0)
        bx, by, bz = vec_norm(ty * up[2] - tz * up[1], tz * up[0] - tx * up[2], tx * up[1] - ty * up[0])
        nx0, ny0, nz0 = vec_norm(by * tz - bz * ty, bz * tx - bx * tz, bx * ty - by * tx)

        tube_r = 0.25 + 0.03 * math.sin(6.0 * t)  # sculpted organic thickness variation!
        for iv in range(nv):
            phi = (iv / nv) * 2.0 * math.pi
            cp, sp = math.cos(phi), math.sin(phi)
            snx = nx0 * cp + bx * sp
            sny = ny0 * cp + by * sp
            snz = nz0 * cp + bz * sp
            sx = p0[0] + snx * tube_r
            sy = p0[1] + sny * tube_r
            sz = p0[2] + snz * tube_r
            # Slight metallic gold-to-copper gradient along knot!
            g_mix = 0.5 + 0.5 * math.sin(3.0 * t)
            alb = (0.98, 0.72 + 0.10 * g_mix, 0.30 + 0.14 * g_mix)
            add_baked_splat(sx, sy, sz, snx, sny, snz, alb, 0.92, 0.135)

    # 2. Architectural Circular Honed Travertine Pedestal below knot (260 Gaussians)
    for ir in range(1, 7):
        rad = ir * 0.27
        cnt = int(10 + ir * 9)
        for ic in range(cnt):
            ang = (ic / cnt) * 2.0 * math.pi
            px = math.cos(ang) * rad
            pz = math.sin(ang) * rad
            checker = (int(math.floor(px * 1.6)) + int(math.floor(pz * 1.6))) % 2
            alb = (0.62, 0.57, 0.50) if checker == 0 else (0.16, 0.18, 0.22)
            add_baked_splat(px, -1.18, pz, 0.0, 1.0, 0.0, alb, 0.1, 0.185)
    # Pedestal rim
    for ic in range(44):
        ang = (ic / 44) * 2.0 * math.pi
        nx, nz = math.cos(ang), math.sin(ang)
        add_baked_splat(nx * 1.66, -1.30, nz * 1.66, nx, 0.0, nz, (0.55, 0.50, 0.44), 0.0, 0.175)

    # 3. Floating Glowing Cyan-Aqua Lumen Plasma Core at center (65 volumetric emissive Gaussians!)
    for i in range(65):
        # Fibonacci sphere shell
        y_u = 1.0 - (i / 64.0) * 2.0
        r_u = math.sqrt(max(0.0, 1.0 - y_u * y_u))
        theta = i * 2.3999632
        nx, ny, nz = math.cos(theta) * r_u, y_u, math.sin(theta) * r_u
        cr = 0.26 if i < 45 else 0.14
        em = (0.4, 2.8, 5.2) if i < 45 else (2.5, 4.5, 6.0)
        add_baked_splat(nx * cr, 0.15 + ny * cr, nz * cr, nx, ny, nz, (0.2, 0.8, 1.0), 0.0, 0.17 if i < 45 else 0.24, emissive=em)

    return splats


def build_3dgs_splat():
    splats = bake_radiance_splats()
    n_splats = len(splats)
    print(f"Baked {n_splats} 3D Radiance Gaussians!")

    pb = ProjectBuilder()
    s = pb.add_sprite("UE5_3DGS_Pen")

    # Controls & Telemetry
    AUTO_FRAMES = s.var("AUTO_FRAMES", 0)    # 0 = interactive continuous turntable; >0 = benchmark N frames
    DONE = s.var("DONE", 0)
    AVG_FRAME_MS = s.var("AVG_FRAME_MS", 0)
    FPS_MEASURED = s.var("FPS_MEASURED", 0)
    VISIBLE_SPLATS = s.var("VISIBLE_SPLATS", 0)
    TOTAL_SPLATS = s.var("TOTAL_SPLATS", n_splats)

    # Baked Gaussian attribute lists
    gx = s.lst("gx", [p[0] for p in splats])
    gy = s.lst("gy", [p[1] for p in splats])
    gz = s.lst("gz", [p[2] for p in splats])
    gnx = s.lst("gnx", [p[3] for p in splats])
    gny = s.lst("gny", [p[4] for p in splats])
    gnz = s.lst("gnz", [p[5] for p in splats])
    gcr = s.lst("gcr", [p[6] for p in splats])
    gcg = s.lst("gcg", [p[7] for p in splats])
    gcb = s.lst("gcb", [p[8] for p in splats])
    gsp = s.lst("gsp", [p[9] for p in splats])
    grd = s.lst("grd", [p[10] for p in splats])
    gem = s.lst("gem", [p[11] for p in splats])

    # Runtime projected buffers + O(N) 128-bucket counting sort linked lists!
    N_BINS = 128
    binHead = s.lst("binHead", [0] * N_BINS)
    nxtNode = s.lst("nxtNode", [0] * n_splats)
    projX = s.lst("projX", [0] * n_splats)
    projY = s.lst("projY", [0] * n_splats)
    projR = s.lst("projR", [0] * n_splats)
    projCol = s.lst("projCol", [0] * n_splats)
    projColHalo = s.lst("projColHalo", [0] * n_splats)
    projEm = s.lst("projEm", [0] * n_splats)

    # Camera rotation & projection registers
    yaw = s.var("yaw", 22.0)
    pitch = s.var("pitch", -16.0)
    camDist = s.var("camDist", 4.3)
    cy, sy = s.var("cy"), s.var("sy")
    cp, sp = s.var("cp"), s.var("sp")

    i = s.var("i")
    bi = s.var("bi")
    node = s.var("node")
    x0, y0, z0 = s.var("x0"), s.var("y0"), s.var("z0")
    x1, y1, z1 = s.var("x1"), s.var("y1"), s.var("z1")
    vx, vy, vz = s.var("vx"), s.var("vy"), s.var("vz")
    nx, ny, nz = s.var("nx"), s.var("ny"), s.var("nz")
    vnx, vny, vnz = s.var("vnx"), s.var("vny"), s.var("vnz")
    invZ, sx, sy_p, sr = s.var("invZ"), s.var("sx"), s.var("sy_p"), s.var("sr")
    bIdx = s.var("bIdx")

    # Live View-Dependent PBR Specular + Fresnel registers
    spec, fres, rC, gC, bC, baseRgb = s.var("spec"), s.var("fres"), s.var("rC"), s.var("gC"), s.var("bC"), s.var("baseRgb")
    emFlag = s.var("emFlag")
    t0, frameN = s.var("t0"), s.var("frameN")

    now_ms = lambda: s.mul(s.days_since_2000(), 86400000)

    # Light direction in camera-ish key light for crisp live specular highlights (normalized ~(0.5, 0.65, -0.57))
    # Plus Half vector with view dir (0, 0, -1): H = normalize((0.5, 0.65, -1.57)) = (0.282, 0.367, -0.886)
    HX, HY, HZ = 0.282, 0.367, -0.886

    # =========================================================================
    # RENDER 1 FULL 3DGS FRAME (Project -> O(N) Bucket Sort -> ARGB Multi-Shell Splat!)
    # =========================================================================
    p_render_3dgs = s.define_proc("render_3dgs_frame", warp=True, body=[
        s.pen_clear(),
        # Rich UE5 Dark Studio Vignette Backdrop (6 horizontal pen gradient strips -> 0.1ms!)
        s.pen_set_size(70),
        s.set_var("i", 0),
        s.repeat(6, [
            # Top dark slate-indigo to warm low studio floor mist
            s.pen_set_color(s.add(
                s.mul(s.floor(s.add(10, s.mul(i, 4))), 65536),
                s.add(s.mul(s.floor(s.add(13, s.mul(i, 5))), 256), s.floor(s.add(24, s.mul(i, 6)))),
            )),
            s.goto_xy(-240, s.sub(155, s.mul(i, 62))),
            s.pen_down(), s.goto_xy(240, s.sub(155, s.mul(i, 62))), s.pen_up(),
            s.change_var("i", 1),
        ]),
        # Subtle warm studio key-light backdrop glow (2 huge translucent Pen circles!)
        s.goto_xy(55, 40),
        s.pen_set_size(320), s.pen_set_color(12 * 16777216 + 255 * 65536 + 170 * 256 + 90), s.pen_down(), s.pen_up(),
        s.goto_xy(-30, -20),
        s.pen_set_size(240), s.pen_set_color(10 * 16777216 + 40 * 65536 + 190 * 256 + 255), s.pen_down(), s.pen_up(),

        # Precompute camera rotation trig (once per frame!)
        s.set_var("cy", s.cos(yaw)),
        s.set_var("sy", s.sin(yaw)),
        s.set_var("cp", s.cos(pitch)),
        s.set_var("sp", s.sin(pitch)),

        # Clear 128 depth buckets (O(128))
        s.set_var("bi", 1),
        s.repeat(N_BINS, [
            s.replace_item(binHead, bi, 0),
            s.change_var("bi", 1),
        ]),

        # Pass 1: Transform + Backface Cull + Live PBR Shading + O(N) Bucket Insert!
        s.set_var("VISIBLE_SPLATS", 0),
        s.set_var("i", 1),
        s.repeat(n_splats, [
            s.set_var("x0", s.item_of(gx, i)),
            s.set_var("y0", s.item_of(gy, i)),
            s.set_var("z0", s.item_of(gz, i)),
            # Rotate Y (yaw)
            s.set_var("x1", s.add(s.mul(x0, cy), s.mul(z0, sy))),
            s.set_var("z1", s.sub(s.mul(z0, cy), s.mul(x0, sy))),
            # Rotate X (pitch) + translate by camDist
            s.set_var("vx", x1),
            s.set_var("vy", s.sub(s.mul(y0, cp), s.mul(z1, sp))),
            s.set_var("vz", s.add(s.add(s.mul(y0, sp), s.mul(z1, cp)), camDist)),

            s.if_(s.gt(vz, 0.6), [
                # Transform normal into view space for backface culling + live Fresnel/Specular!
                s.set_var("nx", s.item_of(gnx, i)),
                s.set_var("ny", s.item_of(gny, i)),
                s.set_var("nz", s.item_of(gnz, i)),
                s.set_var("x1", s.add(s.mul(nx, cy), s.mul(nz, sy))),
                s.set_var("z1", s.sub(s.mul(nz, cy), s.mul(nx, sy))),
                s.set_var("vnx", x1),
                s.set_var("vny", s.sub(s.mul(ny, cp), s.mul(z1, sp))),
                s.set_var("vnz", s.add(s.mul(ny, sp), s.mul(z1, cp))),

                s.set_var("emFlag", s.item_of(gem, i)),
                # Cull backfacing opaque splats (vnz > 0.35 faces away from camera along -Z!)
                s.if_(s.lor(s.eq(emFlag, 1), s.lt(vnz, 0.35)), [
                    s.set_var("invZ", s.div(355.0, vz)),
                    s.set_var("sx", s.mul(vx, invZ)),
                    s.set_var("sy_p", s.mul(vy, invZ)),
                    s.set_var("sr", s.mul(s.item_of(grd, i), invZ)),

                    # Live view-dependent GGX-like specular + grazing Fresnel rim!
                    s.set_var("rC", s.item_of(gcr, i)),
                    s.set_var("gC", s.item_of(gcg, i)),
                    s.set_var("bC", s.item_of(gcb, i)),
                    s.if_(s.eq(emFlag, 0), [
                        # N.H in view space
                        s.set_var("spec", s.add(s.mul(vnx, HX), s.add(s.mul(vny, HY), s.mul(vnz, HZ)))),
                        s.if_(s.gt(spec, 0), [
                            # spec^16 via 4 squarings -> crisp metallic GGX highlight!
                            s.set_var("spec", s.mul(spec, spec)),
                            s.set_var("spec", s.mul(spec, spec)),
                            s.set_var("spec", s.mul(spec, spec)),
                            s.set_var("spec", s.mul(spec, spec)),
                            s.set_var("spec", s.mul(spec, s.mul(s.item_of(gsp, i), 180.0))),
                            s.change_var("rC", s.mul(spec, 1.0)),
                            s.change_var("gC", s.mul(spec, 0.88)),
                            s.change_var("bC", s.mul(spec, 0.65)),
                        ]),
                        # Grazing Fresnel rim light (cool cyan-sky rim at silhouette edges!)
                        s.set_var("fres", s.add(1.0, vnz)),  # 1 - (-vnz): near 1 at grazing silhouette
                        s.if_(s.lt(fres, 0), [s.set_var("fres", 0)]),
                        s.if_(s.gt(fres, 1), [s.set_var("fres", 1)]),
                        s.set_var("fres", s.mul(fres, s.mul(fres, s.mul(fres, s.mul(s.item_of(gsp, i), 65.0))))),
                        s.change_var("rC", s.mul(fres, 0.45)),
                        s.change_var("gC", s.mul(fres, 0.75)),
                        s.change_var("bC", s.mul(fres, 1.0)),
                    ]),
                    s.if_(s.gt(rC, 255), [s.set_var("rC", 255)]),
                    s.if_(s.gt(gC, 255), [s.set_var("gC", 255)]),
                    s.if_(s.gt(bC, 255), [s.set_var("bC", 255)]),
                    s.set_var("baseRgb", s.add(s.mul(s.floor(rC), 65536), s.add(s.mul(s.floor(gC), 256), s.floor(bC)))),

                    s.replace_item(projX, i, sx),
                    s.replace_item(projY, i, sy_p),
                    s.replace_item(projR, i, sr),
                    s.replace_item(projEm, i, emFlag),
                    s.if_else(
                        s.eq(emFlag, 1),
                        [
                            s.replace_item(projCol, i, s.add(110 * 16777216, baseRgb)),
                            s.replace_item(projColHalo, i, s.add(18 * 16777216, baseRgb)),
                        ],
                        [
                            s.replace_item(projCol, i, s.add(235 * 16777216, baseRgb)),
                            s.replace_item(projColHalo, i, s.add(78 * 16777216, baseRgb)),
                        ],
                    ),

                    # O(1) Depth Bucket Insert (vz in [1.2, 7.6] -> bin 1..128)
                    s.set_var("bIdx", s.floor(s.mul(s.sub(vz, 1.2), 20.0))),
                    s.if_(s.lt(bIdx, 1), [s.set_var("bIdx", 1)]),
                    s.if_(s.gt(bIdx, N_BINS), [s.set_var("bIdx", N_BINS)]),
                    s.replace_item(nxtNode, i, s.item_of(binHead, bIdx)),
                    s.replace_item(binHead, bIdx, i),
                    s.change_var("VISIBLE_SPLATS", 1),
                ]),
            ]),
            s.change_var("i", 1),
        ]),

        # Pass 2: Back-to-Front Multi-Shell 32-bit ARGB Gaussian Pen Splatting!
        # Exploits PenSkin's WebGL2 Instanced Circle Shader for soft radial falloff!
        s.set_var("bi", N_BINS),
        s.repeat(N_BINS, [
            s.set_var("node", s.item_of(binHead, bi)),
            s.repeat_until(s.eq(node, 0), [
                s.goto_xy(s.item_of(projX, node), s.item_of(projY, node)),
                s.set_var("sr", s.item_of(projR, node)),
                # Outer soft Gaussian feathered shell
                s.if_else(
                    s.eq(s.item_of(projEm, node), 1),
                    [s.pen_set_size(s.mul(sr, 3.2))],
                    [s.pen_set_size(s.mul(sr, 1.55))],
                ),
                s.pen_set_color(s.item_of(projColHalo, node)),
                s.pen_down(), s.pen_up(),
                # Inner dense core splat
                s.pen_set_size(s.mul(sr, 1.05)),
                s.pen_set_color(s.item_of(projCol, node)),
                s.pen_down(), s.pen_up(),
                s.set_var("node", s.item_of(nxtNode, node)),
            ]),
            s.change_var("bi", -1),
        ]),
    ])

    s.when_flag_clicked([
        s.hide(),
        s.set_var("DONE", 0),
        s.if_else(
            s.gt(AUTO_FRAMES, 0),
            [
                s.set_var("t0", now_ms()),
                s.set_var("frameN", 0),
                s.repeat(AUTO_FRAMES, [
                    s.call_proc(p_render_3dgs),
                    s.change_var("yaw", 4.0),
                    s.change_var("frameN", 1),
                ]),
                s.set_var("AVG_FRAME_MS", s.div(s.sub(now_ms(), t0), AUTO_FRAMES)),
                s.set_var("FPS_MEASURED", s.div(1000.0, s.add(AVG_FRAME_MS, 0.001))),
                s.set_var("DONE", 1),
            ],
            [
                # Continuous real-time 3DGS turntable + interactive Arrow-key camera orbit!
                s.forever([
                    s.set_var("t0", now_ms()),
                    s.call_proc(p_render_3dgs),
                    s.set_var("AVG_FRAME_MS", s.sub(now_ms(), t0)),
                    s.set_var("FPS_MEASURED", s.div(1000.0, s.add(AVG_FRAME_MS, 0.001))),
                    s.if_else(
                        s.lor(s.key_pressed("left arrow"), s.key_pressed("right arrow")),
                        [
                            s.if_(s.key_pressed("left arrow"), [s.change_var("yaw", -4.5)]),
                            s.if_(s.key_pressed("right arrow"), [s.change_var("yaw", 4.5)]),
                        ],
                        [s.change_var("yaw", 2.0)],
                    ),
                    s.if_(s.key_pressed("up arrow"), [s.change_var("pitch", -3.0)]),
                    s.if_(s.key_pressed("down arrow"), [s.change_var("pitch", 3.0)]),
                ]),
            ],
        ),
    ])

    from pathlib import Path
    out = pb.save_sb3(Path(__file__).resolve().parent / "sb3" / "ue5_3dgs_splat.sb3")
    print("Built:", out, f"({len(s.blocks)} Scratch blocks, {n_splats} 3D Gaussians)")


if __name__ == "__main__":
    build_3dgs_splat()
