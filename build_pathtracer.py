"""
build_pathtracer.py — Builds out/ue5_pathtracer.sb3

A True Monte Carlo Path Tracer in 100% Pure Vanilla Scratch Pen:
  - Analytic Ray-Plane / Ray-Sphere / Ray-Box intersection (~10x faster per ray than SDF march!)
  - Multi-bounce Global Illumination (up to 3 bounces) with:
      * Cosine-weighted hemisphere diffuse sampling
      * Glossy/Mirror GGX-like cone-perturbed metallic reflection
      * Next-Event Estimation (NEE) direct area-light shadow sampling for dramatic variance reduction!
  - Thin-Lens Depth of Field (Bokeh)
  - Dual Accumulation Architecture for Empirical Comparison:
      * ACCUM_MODE=0: HDR Linear Float List Buffer (accR/accG/accB) -> ACES Filmic -> Gamma -> Pen
      * ACCUM_MODE=1: Zero-List Direct 32-bit ARGB Pen Alpha Blending (alpha = 255 / spp)
  - Showcases true multi-bounce color bleeding (crimson left wall + cyan-teal right wall),
    ultra-soft physical area shadows, mirror chrome reflections, and rough brushed-gold specular blur!
"""

from sb3_builder import ProjectBuilder


def clamp01_stmts(s, vname):
    v = s.var(vname)
    return [
        s.if_(s.lt(v, 0), [s.set_var(vname, 0)]),
        s.if_(s.gt(v, 1), [s.set_var(vname, 1)]),
    ]


def clamp_stmts(s, vname, lo, hi):
    v = s.var(vname)
    return [
        s.if_(s.lt(v, lo), [s.set_var(vname, lo)]),
        s.if_(s.gt(v, hi), [s.set_var(vname, hi)]),
    ]


def build_pathtracer():
    pb = ProjectBuilder()
    s = pb.add_sprite("UE5_PathTracer_Pen")

    # Controls & Telemetry
    TARGET_SPP = s.var("TARGET_SPP", 32)     # 1, 4, 16, 32, 64
    PIXEL_STEP = s.var("PIXEL_STEP", 2)      # 2 = 240x180 (43,200 px), 1 = 480x360 (172,800 px)
    ACCUM_MODE = s.var("ACCUM_MODE", 0)      # 0 = HDR Float List Buffer, 1 = Direct Pen ARGB Alpha
    DENOISE = s.var("DENOISE", 1)            # 1 = 3x3 Edge-Stopping Bilateral Denoiser (SVGF-lite)
    DOF_APERTURE = s.var("DOF_APERTURE", 0.045)
    DONE = s.var("DONE", 0)
    SPP_DONE = s.var("SPP_DONE", 0)
    TOTAL_MS = s.var("TOTAL_MS", 0)
    MS_PER_SPP = s.var("MS_PER_SPP", 0)
    DENOISE_MS = s.var("DENOISE_MS", 0)
    # Bilateral denoiser registers
    cR, cG, cB = s.var("cR"), s.var("cG"), s.var("cB")
    sR, sG, sB, wSum = s.var("sR"), s.var("sG"), s.var("sB"), s.var("wSum")
    nR, nG, nB, nW, dCol = s.var("nR"), s.var("nG"), s.var("nB"), s.var("nW"), s.var("dCol")
    dx, dy, nIdx, tD0 = s.var("dx"), s.var("dy"), s.var("nIdx"), s.var("tD0")

    # HDR Float Accumulation Lists (43,200 items at step=2, fits easily in Vanilla 200k limit!)
    accR = s.lst("accR")
    accG = s.lst("accG")
    accB = s.lst("accB")

    # Camera (Cornell-Sanctuary chamber: x in [-2.2, 2.2], y in [-1.5, 2.2], z in [-4.5, 2.6])
    CAM_X, CAM_Y, CAM_Z = 0.0, 0.25, -4.15
    FOCUS_DIST = 4.55

    # Area light on ceiling: y = 2.19, x in [-0.85, 0.85], z in [-0.55, 1.15]
    # Area = 1.7 * 1.7 = 2.89, HDR Radiance = (13.5, 11.8, 9.6)
    L_Y = 2.19
    L_X0, L_X1 = -0.85, 0.85
    L_Z0, L_Z1 = -0.55, 1.15
    L_EM_R, L_EM_G, L_EM_B = 13.5, 11.8, 9.6

    # Working registers
    roX, roY, roZ = s.var("roX"), s.var("roY"), s.var("roZ")
    rdX, rdY, rdZ = s.var("rdX"), s.var("rdY"), s.var("rdZ")
    hitT, hitMat = s.var("hitT"), s.var("hitMat")
    hitX, hitY, hitZ = s.var("hitX"), s.var("hitY"), s.var("hitZ")
    nX, nY, nZ = s.var("nX"), s.var("nY"), s.var("nZ")

    # Material registers
    albR, albG, albB = s.var("albR"), s.var("albG"), s.var("albB")
    metal, rough = s.var("metal"), s.var("rough")
    isEmit = s.var("isEmit")

    # Path state
    thrR, thrG, thrB = s.var("thrR"), s.var("thrG"), s.var("thrB")
    radR, radG, radB = s.var("radR"), s.var("radG"), s.var("radB")
    bounce = s.var("bounce")

    # NEE shadow ray state
    lx, ly, lz = s.var("lx"), s.var("ly"), s.var("lz")
    ldX, ldY, ldZ = s.var("ldX"), s.var("ldY"), s.var("ldZ")
    lDist, lDist2, nDotL, lCos, neeW = s.var("lDist"), s.var("lDist2"), s.var("nDotL"), s.var("lCos"), s.var("neeW")
    sHitT, sHitMat = s.var("sHitT"), s.var("sHitMat")

    # Temp math / PRNG
    rng = s.var("rng", 1234567)
    r1, r2, r3 = s.var("r1"), s.var("r2"), s.var("r3")
    rx, ry, rz = s.var("rx"), s.var("ry"), s.var("rz")
    tTmp, bTmp, cTmp, disc, sqD, invL = (
        s.var("tTmp"), s.var("bTmp"), s.var("cTmp"), s.var("disc"), s.var("sqD"), s.var("invL")
    )
    hx, hy, hz = s.var("hx"), s.var("hy"), s.var("hz")
    dTmp = s.var("dTmp")

    # Screen / Loop vars
    colsN, rowsN, totalPx = s.var("colsN"), s.var("rowsN"), s.var("totalPx")
    px, py, pIdx = s.var("px"), s.var("py"), s.var("pIdx")
    scrX, scrY = s.var("scrX"), s.var("scrY")
    u, v, spp = s.var("u"), s.var("v"), s.var("spp")
    pR, pG, pB = s.var("pR"), s.var("pG"), s.var("pB")
    invSpp, alphaByte, outCol, bayer = s.var("invSpp"), s.var("alphaByte"), s.var("outCol"), s.var("bayer")
    t0 = s.var("t0")

    now_ms = lambda: s.mul(s.days_since_2000(), 86400000)

    # Fast LCG PRNG in [0, 1) (faster and deterministic compared to Scratch's pick random!)
    def next_rand(out_var):
        return [
            s.set_var("rng", s.mod(s.add(s.mul(rng, 1664525), 1013904223), 4294967296)),
            s.set_var(out_var, s.div(rng, 4294967296.0)),
        ]

    # Helper: Ray-Sphere intersection statements (center cx, cy, cz, radius R, matId)
    def intersect_sphere(cx, cy, cz, radius, mat_id):
        r2_val = radius * radius
        return [
            s.set_var("hx", s.sub(roX, cx)),
            s.set_var("hy", s.sub(roY, cy)),
            s.set_var("hz", s.sub(roZ, cz)),
            s.set_var("bTmp", s.add(s.mul(hx, rdX), s.add(s.mul(hy, rdY), s.mul(hz, rdZ)))),
            s.set_var("cTmp", s.sub(s.add(s.mul(hx, hx), s.add(s.mul(hy, hy), s.mul(hz, hz))), r2_val)),
            s.set_var("disc", s.sub(s.mul(bTmp, bTmp), cTmp)),
            s.if_(s.gt(disc, 0), [
                s.set_var("sqD", s.sqrt(disc)),
                s.set_var("tTmp", s.sub(s.mul(bTmp, -1), sqD)),
                s.if_(s.land(s.gt(tTmp, 0.002), s.lt(tTmp, hitT)), [
                    s.set_var("hitT", tTmp),
                    s.set_var("hitMat", mat_id),
                    s.set_var("hitX", s.add(roX, s.mul(rdX, tTmp))),
                    s.set_var("hitY", s.add(roY, s.mul(rdY, tTmp))),
                    s.set_var("hitZ", s.add(roZ, s.mul(rdZ, tTmp))),
                    s.set_var("invL", 1.0 / radius),
                    s.set_var("nX", s.mul(s.sub(hitX, cx), invL)),
                    s.set_var("nY", s.mul(s.sub(hitY, cy), invL)),
                    s.set_var("nZ", s.mul(s.sub(hitZ, cz), invL)),
                ]),
            ]),
        ]

    # =========================================================================
    # 1. ANALYTIC SCENE INTERSECTOR: intersect_scene() using roX..rdZ
    #    Sets hitT, hitMat, hitX..hitZ, nX..nZ
    #    Materials:
    #      1=Floor (travertine), 2=Ceiling, 3=Back Wall, 4=Left Crimson Wall,
    #      5=Right Cyan-Teal Wall, 6=Ceiling Area Light,
    #      7=Mirror Chrome Sphere, 8=Brushed Gold Glossy Sphere, 9=Matte Ceramic Sphere,
    #      10=Warm Amber Emissive Accent Orb
    # =========================================================================
    p_intersect = s.define_proc("intersect_scene", warp=True, body=[
        s.set_var("hitT", 1000.0),
        s.set_var("hitMat", 0),

        # Floor: y = -1.5, N = (0, 1, 0)
        s.if_(s.lt(rdY, -0.0001), [
            s.set_var("tTmp", s.div(s.sub(-1.5, roY), rdY)),
            s.if_(s.land(s.gt(tTmp, 0.002), s.lt(tTmp, hitT)), [
                s.set_var("hitT", tTmp), s.set_var("hitMat", 1),
                s.set_var("hitX", s.add(roX, s.mul(rdX, tTmp))),
                s.set_var("hitY", -1.5),
                s.set_var("hitZ", s.add(roZ, s.mul(rdZ, tTmp))),
                s.set_var("nX", 0), s.set_var("nY", 1), s.set_var("nZ", 0),
            ]),
        ]),

        # Ceiling: y = 2.2, N = (0, -1, 0) + Area Light patch!
        s.if_(s.gt(rdY, 0.0001), [
            s.set_var("tTmp", s.div(s.sub(2.2, roY), rdY)),
            s.if_(s.land(s.gt(tTmp, 0.002), s.lt(tTmp, hitT)), [
                s.set_var("hx", s.add(roX, s.mul(rdX, tTmp))),
                s.set_var("hz", s.add(roZ, s.mul(rdZ, tTmp))),
                s.set_var("hitT", tTmp),
                s.set_var("hitX", hx), s.set_var("hitY", 2.2), s.set_var("hitZ", hz),
                s.set_var("nX", 0), s.set_var("nY", -1), s.set_var("nZ", 0),
                s.if_else(
                    s.land(s.land(s.gt(hx, L_X0), s.lt(hx, L_X1)), s.land(s.gt(hz, L_Z0), s.lt(hz, L_Z1))),
                    [s.set_var("hitMat", 6)],
                    [s.set_var("hitMat", 2)],
                ),
            ]),
        ]),

        # Back Wall: z = 2.6, N = (0, 0, -1)
        s.if_(s.gt(rdZ, 0.0001), [
            s.set_var("tTmp", s.div(s.sub(2.6, roZ), rdZ)),
            s.if_(s.land(s.gt(tTmp, 0.002), s.lt(tTmp, hitT)), [
                s.set_var("hitT", tTmp), s.set_var("hitMat", 3),
                s.set_var("hitX", s.add(roX, s.mul(rdX, tTmp))),
                s.set_var("hitY", s.add(roY, s.mul(rdY, tTmp))),
                s.set_var("hitZ", 2.6),
                s.set_var("nX", 0), s.set_var("nY", 0), s.set_var("nZ", -1),
            ]),
        ]),

        # Front Wall behind camera: z = -4.6, N = (0, 0, 1) (keeps reflections enclosed!)
        s.if_(s.lt(rdZ, -0.0001), [
            s.set_var("tTmp", s.div(s.sub(-4.6, roZ), rdZ)),
            s.if_(s.land(s.gt(tTmp, 0.002), s.lt(tTmp, hitT)), [
                s.set_var("hitT", tTmp), s.set_var("hitMat", 3),
                s.set_var("hitX", s.add(roX, s.mul(rdX, tTmp))),
                s.set_var("hitY", s.add(roY, s.mul(rdY, tTmp))),
                s.set_var("hitZ", -4.6),
                s.set_var("nX", 0), s.set_var("nY", 0), s.set_var("nZ", 1),
            ]),
        ]),

        # Left Crimson-Terracotta Wall: x = -2.25, N = (1, 0, 0)
        s.if_(s.lt(rdX, -0.0001), [
            s.set_var("tTmp", s.div(s.sub(-2.25, roX), rdX)),
            s.if_(s.land(s.gt(tTmp, 0.002), s.lt(tTmp, hitT)), [
                s.set_var("hitT", tTmp), s.set_var("hitMat", 4),
                s.set_var("hitX", -2.25),
                s.set_var("hitY", s.add(roY, s.mul(rdY, tTmp))),
                s.set_var("hitZ", s.add(roZ, s.mul(rdZ, tTmp))),
                s.set_var("nX", 1), s.set_var("nY", 0), s.set_var("nZ", 0),
            ]),
        ]),

        # Right Emerald-Cyan Wall: x = 2.25, N = (-1, 0, 0)
        s.if_(s.gt(rdX, 0.0001), [
            s.set_var("tTmp", s.div(s.sub(2.25, roX), rdX)),
            s.if_(s.land(s.gt(tTmp, 0.002), s.lt(tTmp, hitT)), [
                s.set_var("hitT", tTmp), s.set_var("hitMat", 5),
                s.set_var("hitX", 2.25),
                s.set_var("hitY", s.add(roY, s.mul(rdY, tTmp))),
                s.set_var("hitZ", s.add(roZ, s.mul(rdZ, tTmp))),
                s.set_var("nX", -1), s.set_var("nY", 0), s.set_var("nZ", 0),
            ]),
        ]),

        # Hero 1: Polished Mirror Chrome Sphere at (-0.82, -0.60, 0.85), r = 0.90
        *intersect_sphere(-0.82, -0.60, 0.85, 0.90, 7),

        # Hero 2: Brushed Gold Glossy Sphere at (0.88, -0.78, 0.35), r = 0.72
        *intersect_sphere(0.88, -0.78, 0.35, 0.72, 8),

        # Hero 3: Matte Alabaster Ceramic Sphere (front-left, showcases GI color bleed!) at (-0.12, -1.02, -0.58), r = 0.48
        *intersect_sphere(-0.12, -1.02, -0.58, 0.48, 9),

        # Hero 4: Warm Amber Floating Emissive Accent Orb at (1.35, 0.65, 1.45), r = 0.24
        *intersect_sphere(1.35, 0.65, 1.45, 0.24, 10),
    ])

    # =========================================================================
    # 2. SHADOW OCCLUSION CHECK FOR NEE (only tests spheres against light ray!)
    #    Sets sHitMat = 1 if occluded before lDist
    # =========================================================================
    def shadow_sphere(cx, cy, cz, radius):
        r2_val = radius * radius
        return [
            s.if_(s.eq(sHitMat, 0), [
                s.set_var("hx", s.sub(hitX, cx)),
                s.set_var("hy", s.sub(hitY, cy)),
                s.set_var("hz", s.sub(hitZ, cz)),
                s.set_var("bTmp", s.add(s.mul(hx, ldX), s.add(s.mul(hy, ldY), s.mul(hz, ldZ)))),
                s.set_var("cTmp", s.sub(s.add(s.mul(hx, hx), s.add(s.mul(hy, hy), s.mul(hz, hz))), r2_val)),
                s.set_var("disc", s.sub(s.mul(bTmp, bTmp), cTmp)),
                s.if_(s.gt(disc, 0), [
                    s.set_var("tTmp", s.sub(s.mul(bTmp, -1), s.sqrt(disc))),
                    s.if_(s.land(s.gt(tTmp, 0.005), s.lt(tTmp, s.sub(lDist, 0.01))), [
                        s.set_var("sHitMat", 1),
                    ]),
                ]),
            ]),
        ]

    p_shadow_occ = s.define_proc("check_shadow", warp=True, body=[
        s.set_var("sHitMat", 0),
        *shadow_sphere(-0.82, -0.60, 0.85, 0.90),
        *shadow_sphere(0.88, -0.78, 0.35, 0.72),
        *shadow_sphere(-0.12, -1.02, -0.58, 0.48),
    ])

    # =========================================================================
    # 3. TRACE 1 MONTE CARLO PATH (up to 3 bounces + NEE!)
    # =========================================================================
    p_trace = s.define_proc("trace_path", warp=True, body=[
        s.set_var("thrR", 1.0), s.set_var("thrG", 1.0), s.set_var("thrB", 1.0),
        s.set_var("radR", 0.0), s.set_var("radG", 0.0), s.set_var("radB", 0.0),
        s.set_var("bounce", 0),
        s.set_var("isEmit", 0),

        s.repeat_until(s.lor(s.gt(bounce, 2), s.eq(isEmit, 1)), [
            s.call_proc(p_intersect),
            s.if_else(
                s.eq(hitMat, 0),
                [s.set_var("isEmit", 1)],
                [
                    # Hit Ceiling Area Light!
                    s.if_else(
                        s.eq(hitMat, 6),
                        [
                            # Only add direct emission on bounce 0 or specular bounce (avoid double-counting NEE!)
                            s.if_(s.lor(s.eq(bounce, 0), s.gt(metal, 0.5)), [
                                s.change_var("radR", s.mul(thrR, L_EM_R)),
                                s.change_var("radG", s.mul(thrG, L_EM_G)),
                                s.change_var("radB", s.mul(thrB, L_EM_B)),
                            ]),
                            s.set_var("isEmit", 1),
                        ],
                        [
                            # Hit Warm Amber Emissive Accent Orb!
                            s.if_else(
                                s.eq(hitMat, 10),
                                [
                                    s.change_var("radR", s.mul(thrR, 9.5)),
                                    s.change_var("radG", s.mul(thrG, 4.2)),
                                    s.change_var("radB", s.mul(thrB, 1.0)),
                                    s.set_var("isEmit", 1),
                                ],
                                [
                                    # Assign PBR material properties
                                    s.set_var("metal", 0.0), s.set_var("rough", 0.9),
                                    s.if_(s.eq(hitMat, 1), [
                                        # Checkered marble floor (slightly glossy dielectric!)
                                        s.set_var("dTmp", s.mod(s.add(s.floor(s.mul(hitX, 1.1)), s.floor(s.mul(hitZ, 1.1))), 2)),
                                        s.if_else(
                                            s.eq(dTmp, 0),
                                            [s.set_var("albR", 0.78), s.set_var("albG", 0.75), s.set_var("albB", 0.71)],
                                            [s.set_var("albR", 0.22), s.set_var("albG", 0.23), s.set_var("albB", 0.26)],
                                        ),
                                    ]),
                                    s.if_(s.eq(hitMat, 2), [s.set_var("albR", 0.80), s.set_var("albG", 0.78), s.set_var("albB", 0.75)]),
                                    s.if_(s.eq(hitMat, 3), [s.set_var("albR", 0.76), s.set_var("albG", 0.74), s.set_var("albB", 0.71)]),
                                    s.if_(s.eq(hitMat, 4), [s.set_var("albR", 0.86), s.set_var("albG", 0.14), s.set_var("albB", 0.11)]),  # Crimson
                                    s.if_(s.eq(hitMat, 5), [s.set_var("albR", 0.10), s.set_var("albG", 0.64), s.set_var("albB", 0.76)]),  # Cyan-Teal
                                    s.if_(s.eq(hitMat, 7), [s.set_var("albR", 0.95), s.set_var("albG", 0.96), s.set_var("albB", 0.98), s.set_var("metal", 1.0), s.set_var("rough", 0.03)]),
                                    s.if_(s.eq(hitMat, 8), [s.set_var("albR", 0.98), s.set_var("albG", 0.75), s.set_var("albB", 0.30), s.set_var("metal", 1.0), s.set_var("rough", 0.22)]),
                                    s.if_(s.eq(hitMat, 9), [s.set_var("albR", 0.92), s.set_var("albG", 0.90), s.set_var("albB", 0.86), s.set_var("metal", 0.0), s.set_var("rough", 0.95)]),

                                    # --- NEXT-EVENT ESTIMATION (NEE) on Diffuse Surfaces! ---
                                    s.if_(s.lt(metal, 0.5), [
                                        *next_rand("r1"),
                                        *next_rand("r2"),
                                        s.set_var("lx", s.add(L_X0, s.mul(r1, L_X1 - L_X0))),
                                        s.set_var("ly", L_Y),
                                        s.set_var("lz", s.add(L_Z0, s.mul(r2, L_Z1 - L_Z0))),
                                        s.set_var("ldX", s.sub(lx, hitX)),
                                        s.set_var("ldY", s.sub(ly, hitY)),
                                        s.set_var("ldZ", s.sub(lz, hitZ)),
                                        s.set_var("lDist2", s.add(s.mul(ldX, ldX), s.add(s.mul(ldY, ldY), s.mul(ldZ, ldZ)))),
                                        s.set_var("lDist", s.sqrt(lDist2)),
                                        s.set_var("invL", s.div(1.0, lDist)),
                                        s.set_var("ldX", s.mul(ldX, invL)),
                                        s.set_var("ldY", s.mul(ldY, invL)),
                                        s.set_var("ldZ", s.mul(ldZ, invL)),
                                        s.set_var("nDotL", s.add(s.mul(nX, ldX), s.add(s.mul(nY, ldY), s.mul(nZ, ldZ)))),
                                        s.set_var("lCos", s.mul(ldY, 1.0)),  # light normal is (0,-1,0), -ld.nL = +ldY
                                        s.if_(s.land(s.gt(nDotL, 0.001), s.gt(lCos, 0.001)), [
                                            s.call_proc(p_shadow_occ),
                                            s.if_(s.eq(sHitMat, 0), [
                                                # NEE weight = (Area / pi) * nDotL * lCos / dist^2  (Area=2.89 -> Area/pi = 0.9199)
                                                s.set_var("neeW", s.div(s.mul(0.9199, s.mul(nDotL, lCos)), lDist2)),
                                                s.if_(s.gt(neeW, 2.2), [s.set_var("neeW", 2.2)]),  # firefly clamp!
                                                s.change_var("radR", s.mul(s.mul(thrR, albR), s.mul(L_EM_R, neeW))),
                                                s.change_var("radG", s.mul(s.mul(thrG, albG), s.mul(L_EM_G, neeW))),
                                                s.change_var("radB", s.mul(s.mul(thrB, albB), s.mul(L_EM_B, neeW))),
                                            ]),
                                        ]),
                                    ]),

                                    # Update throughput
                                    s.set_var("thrR", s.mul(thrR, albR)),
                                    s.set_var("thrG", s.mul(thrG, albG)),
                                    s.set_var("thrB", s.mul(thrB, albB)),

                                    # Generate random unit vector (sphere point via cylindrical projection -> ZERO rejection!)
                                    *next_rand("r1"),
                                    *next_rand("r2"),
                                    s.set_var("ry", s.sub(s.mul(r1, 2.0), 1.0)),
                                    s.set_var("dTmp", s.sqrt(s.sub(1.0, s.mul(ry, ry)))),
                                    s.set_var("r3", s.mul(r2, 360.0)),
                                    s.set_var("rx", s.mul(dTmp, s.cos(r3))),
                                    s.set_var("rz", s.mul(dTmp, s.sin(r3))),

                                    # Next ray origin offset slightly along normal
                                    s.set_var("roX", s.add(hitX, s.mul(nX, 0.004))),
                                    s.set_var("roY", s.add(hitY, s.mul(nY, 0.004))),
                                    s.set_var("roZ", s.add(hitZ, s.mul(nZ, 0.004))),

                                    s.if_else(
                                        s.gt(metal, 0.5),
                                        [
                                            # Glossy / Mirror Metallic Reflection: R = rd - 2*(rd.N)*N + rough * randUnitVec
                                            s.set_var("dTmp", s.mul(2.0, s.add(s.mul(rdX, nX), s.add(s.mul(rdY, nY), s.mul(rdZ, nZ))))),
                                            s.set_var("rdX", s.add(s.sub(rdX, s.mul(dTmp, nX)), s.mul(rx, rough))),
                                            s.set_var("rdY", s.add(s.sub(rdY, s.mul(dTmp, nY)), s.mul(ry, rough))),
                                            s.set_var("rdZ", s.add(s.sub(rdZ, s.mul(dTmp, nZ)), s.mul(rz, rough))),
                                        ],
                                        [
                                            # Exact Cosine-Weighted Hemisphere Sampling: normalize(N + randUnitVec)!
                                            s.set_var("rdX", s.add(nX, rx)),
                                            s.set_var("rdY", s.add(nY, ry)),
                                            s.set_var("rdZ", s.add(nZ, rz)),
                                        ],
                                    ),
                                    s.set_var("invL", s.div(1.0, s.add(0.00001, s.sqrt(s.add(s.mul(rdX, rdX), s.add(s.mul(rdY, rdY), s.mul(rdZ, rdZ))))))),
                                    s.set_var("rdX", s.mul(rdX, invL)),
                                    s.set_var("rdY", s.mul(rdY, invL)),
                                    s.set_var("rdZ", s.mul(rdZ, invL)),
                                    s.change_var("bounce", 1),
                                ],
                            ),
                        ],
                    ),
                ],
            ),
        ]),
    ])

    # =========================================================================
    # 4. RUN ONE PROGRESSIVE SPP PASS ACROSS ENTIRE FRAME & DISPLAY VIA PEN!
    # =========================================================================
    p_init_buf = s.define_proc("init_buffers", warp=True, body=[
        s.set_var("colsN", s.floor(s.div(480, PIXEL_STEP))),
        s.set_var("rowsN", s.floor(s.div(360, PIXEL_STEP))),
        s.set_var("totalPx", s.mul(colsN, rowsN)),
        s.delete_all_list(accR), s.delete_all_list(accG), s.delete_all_list(accB),
        s.if_(s.eq(ACCUM_MODE, 0), [
            s.repeat(totalPx, [
                s.add_to_list(accR, 0),
                s.add_to_list(accG, 0),
                s.add_to_list(accB, 0),
            ]),
        ]),
        s.pen_clear(),
    ])

    p_pass_row = s.define_proc("trace_row", ["rowIdx"], warp=True, body=[
        s.set_var("py", s.arg("rowIdx")),
        s.set_var("scrY", s.sub(180, s.add(s.mul(py, PIXEL_STEP), s.mul(PIXEL_STEP, 0.5)))),
        s.set_var("pIdx", s.add(s.mul(py, colsN), 1)),
        s.pen_set_size(PIXEL_STEP),
        s.set_var("px", 0),
        s.set_var("scrX", s.add(-240, s.mul(PIXEL_STEP, 0.5))),
        s.goto_xy(scrX, scrY),

        s.repeat(colsN, [
            # Subpixel Anti-Aliasing Jitter!
            *next_rand("r1"),
            *next_rand("r2"),
            s.set_var("u", s.div(s.add(scrX, s.mul(s.sub(r1, 0.5), PIXEL_STEP)), 180.0)),
            s.set_var("v", s.div(s.add(scrY, s.mul(s.sub(r2, 0.5), PIXEL_STEP)), 180.0)),

            # Primary ray dir (FOV = 1.65)
            s.set_var("rdX", u),
            s.set_var("rdY", s.sub(v, 0.08)),
            s.set_var("rdZ", 1.65),
            s.set_var("invL", s.div(1.0, s.sqrt(s.add(s.mul(rdX, rdX), s.add(s.mul(rdY, rdY), s.mul(rdZ, rdZ)))))),
            s.set_var("rdX", s.mul(rdX, invL)),
            s.set_var("rdY", s.mul(rdY, invL)),
            s.set_var("rdZ", s.mul(rdZ, invL)),

            # Thin-Lens Depth of Field (Bokeh)!
            s.set_var("roX", CAM_X), s.set_var("roY", CAM_Y), s.set_var("roZ", CAM_Z),
            s.if_(s.gt(DOF_APERTURE, 0.0001), [
                *next_rand("r1"),
                *next_rand("r2"),
                s.set_var("dTmp", s.mul(DOF_APERTURE, s.sqrt(r1))),
                s.set_var("r3", s.mul(r2, 360.0)),
                s.set_var("rx", s.mul(dTmp, s.cos(r3))),
                s.set_var("ry", s.mul(dTmp, s.sin(r3))),
                # Focus point P = CAM + rd * FOCUS_DIST
                s.set_var("roX", s.add(CAM_X, rx)),
                s.set_var("roY", s.add(CAM_Y, ry)),
                s.set_var("rdX", s.sub(s.mul(rdX, FOCUS_DIST), rx)),
                s.set_var("rdY", s.sub(s.mul(rdY, FOCUS_DIST), ry)),
                s.set_var("rdZ", s.mul(rdZ, FOCUS_DIST)),
                s.set_var("invL", s.div(1.0, s.sqrt(s.add(s.mul(rdX, rdX), s.add(s.mul(rdY, rdY), s.mul(rdZ, rdZ)))))),
                s.set_var("rdX", s.mul(rdX, invL)),
                s.set_var("rdY", s.mul(rdY, invL)),
                s.set_var("rdZ", s.mul(rdZ, invL)),
            ]),

            s.call_proc(p_trace),

            s.if_else(
                s.eq(ACCUM_MODE, 0),
                [
                    # HDR Linear Float List Accumulation!
                    s.set_var("pR", s.add(s.item_of(accR, pIdx), radR)),
                    s.set_var("pG", s.add(s.item_of(accG, pIdx), radG)),
                    s.set_var("pB", s.add(s.item_of(accB, pIdx), radB)),
                    s.replace_item(accR, pIdx, pR),
                    s.replace_item(accG, pIdx, pG),
                    s.replace_item(accB, pIdx, pB),
                    # Draw live progressive preview at SPP 1, 4, 8, 16 (and final SPP when DENOISE == 0)
                    s.if_(
                        s.lor(
                            s.lor(s.eq(spp, 1), s.eq(spp, 4)),
                            s.lor(s.lor(s.eq(spp, 8), s.eq(spp, 16)), s.land(s.eq(spp, TARGET_SPP), s.eq(DENOISE, 0))),
                        ),
                        [
                            s.set_var("pR", s.mul(pR, invSpp)),
                            s.set_var("pG", s.mul(pG, invSpp)),
                            s.set_var("pB", s.mul(pB, invSpp)),
                            # Exposure 0.72 + ACES Filmic
                            s.set_var("pR", s.mul(pR, 0.72)),
                            s.set_var("pG", s.mul(pG, 0.72)),
                            s.set_var("pB", s.mul(pB, 0.72)),
                            s.set_var("pR", s.div(s.mul(pR, s.add(s.mul(2.51, pR), 0.03)), s.add(s.mul(pR, s.add(s.mul(2.43, pR), 0.59)), 0.14))),
                            s.set_var("pG", s.div(s.mul(pG, s.add(s.mul(2.51, pG), 0.03)), s.add(s.mul(pG, s.add(s.mul(2.43, pG), 0.59)), 0.14))),
                            s.set_var("pB", s.div(s.mul(pB, s.add(s.mul(2.51, pB), 0.03)), s.add(s.mul(pB, s.add(s.mul(2.43, pB), 0.59)), 0.14))),
                            *clamp01_stmts(s, "pR"), *clamp01_stmts(s, "pG"), *clamp01_stmts(s, "pB"),
                            s.set_var("bayer", s.sub(s.mul(s.add(s.mul(s.mod(px, 2), 2), s.mod(py, 2)), 0.25), 0.375)),
                            s.set_var("pR", s.floor(s.add(s.mul(s.sqrt(pR), 255.0), bayer))),
                            s.set_var("pG", s.floor(s.add(s.mul(s.sqrt(pG), 255.0), bayer))),
                            s.set_var("pB", s.floor(s.add(s.mul(s.sqrt(pB), 255.0), bayer))),
                            *clamp_stmts(s, "pR", 0, 255), *clamp_stmts(s, "pG", 0, 255), *clamp_stmts(s, "pB", 0, 255),
                            s.set_var("outCol", s.add(s.mul(pR, 65536), s.add(s.mul(pG, 256), pB))),
                            s.pen_set_color(outCol),
                            s.if_(s.eq(px, 0), [s.pen_down()]),
                            s.change_x(PIXEL_STEP),
                        ],
                    ),
                ],
                [
                    # ACCUM_MODE=1: Direct 32-bit ARGB Pen Alpha Blending (zero list memory!)
                    s.set_var("pR", s.mul(radR, 0.72)),
                    s.set_var("pG", s.mul(radG, 0.72)),
                    s.set_var("pB", s.mul(radB, 0.72)),
                    s.set_var("pR", s.div(s.mul(pR, s.add(s.mul(2.51, pR), 0.03)), s.add(s.mul(pR, s.add(s.mul(2.43, pR), 0.59)), 0.14))),
                    s.set_var("pG", s.div(s.mul(pG, s.add(s.mul(2.51, pG), 0.03)), s.add(s.mul(pG, s.add(s.mul(2.43, pG), 0.59)), 0.14))),
                    s.set_var("pB", s.div(s.mul(pB, s.add(s.mul(2.51, pB), 0.03)), s.add(s.mul(pB, s.add(s.mul(2.43, pB), 0.59)), 0.14))),
                    *clamp01_stmts(s, "pR"), *clamp01_stmts(s, "pG"), *clamp01_stmts(s, "pB"),
                    s.set_var("pR", s.floor(s.mul(s.sqrt(pR), 255.0))),
                    s.set_var("pG", s.floor(s.mul(s.sqrt(pG), 255.0))),
                    s.set_var("pB", s.floor(s.mul(s.sqrt(pB), 255.0))),
                    *clamp_stmts(s, "pR", 0, 255), *clamp_stmts(s, "pG", 0, 255), *clamp_stmts(s, "pB", 0, 255),
                    s.set_var("outCol", s.add(s.mul(alphaByte, 16777216), s.add(s.mul(pR, 65536), s.add(s.mul(pG, 256), pB)))),
                    s.pen_set_color(outCol),
                    s.if_(s.eq(px, 0), [s.pen_down()]),
                    s.change_x(PIXEL_STEP),
                ],
            ),

            s.change_var("scrX", PIXEL_STEP),
            s.change_var("px", 1),
            s.change_var("pIdx", 1),
        ]),
        s.pen_up(),
    ])

    # =========================================================================
    # 5. EDGE-STOPPING 3x3 BILATERAL DENOISER (SVGF-LITE) + PEN DISPLAY!
    # =========================================================================
    p_denoise = s.define_proc("denoise_and_display", warp=True, body=[
        s.set_var("tD0", now_ms()),
        s.set_var("invSpp", s.div(0.72, TARGET_SPP)),
        # Step A: Tone-map HDR float buffer into perceptual gamma space in-place (O(N))
        s.set_var("pIdx", 1),
        s.repeat(totalPx, [
            s.set_var("pR", s.mul(s.item_of(accR, pIdx), invSpp)),
            s.set_var("pG", s.mul(s.item_of(accG, pIdx), invSpp)),
            s.set_var("pB", s.mul(s.item_of(accB, pIdx), invSpp)),
            s.set_var("pR", s.div(s.mul(pR, s.add(s.mul(2.51, pR), 0.03)), s.add(s.mul(pR, s.add(s.mul(2.43, pR), 0.59)), 0.14))),
            s.set_var("pG", s.div(s.mul(pG, s.add(s.mul(2.51, pG), 0.03)), s.add(s.mul(pG, s.add(s.mul(2.43, pG), 0.59)), 0.14))),
            s.set_var("pB", s.div(s.mul(pB, s.add(s.mul(2.51, pB), 0.03)), s.add(s.mul(pB, s.add(s.mul(2.43, pB), 0.59)), 0.14))),
            *clamp01_stmts(s, "pR"), *clamp01_stmts(s, "pG"), *clamp01_stmts(s, "pB"),
            s.replace_item(accR, pIdx, s.sqrt(pR)),
            s.replace_item(accG, pIdx, s.sqrt(pG)),
            s.replace_item(accB, pIdx, s.sqrt(pB)),
            s.change_var("pIdx", 1),
        ]),

        # Step B: 3x3 Edge-Stopping Bilateral Filter (sigma_c = 0.16) + Continuous Pen Scanline Output!
        s.pen_set_size(PIXEL_STEP),
        s.set_var("py", 0),
        s.repeat(rowsN, [
            s.set_var("scrY", s.sub(180, s.add(s.mul(py, PIXEL_STEP), s.mul(PIXEL_STEP, 0.5)))),
            s.set_var("scrX", s.add(-240, s.mul(PIXEL_STEP, 0.5))),
            s.goto_xy(scrX, scrY),
            s.set_var("px", 0),
            s.set_var("pIdx", s.add(s.mul(py, colsN), 1)),
            s.repeat(colsN, [
                s.set_var("cR", s.item_of(accR, pIdx)),
                s.set_var("cG", s.item_of(accG, pIdx)),
                s.set_var("cB", s.item_of(accB, pIdx)),
                s.set_var("sR", cR), s.set_var("sG", cG), s.set_var("sB", cB),
                s.set_var("wSum", 1.0),
                # Only filter interior pixels (1..colsN-2, 1..rowsN-2)
                s.if_(s.land(s.land(s.gt(px, 0), s.lt(px, s.sub(colsN, 1))), s.land(s.gt(py, 0), s.lt(py, s.sub(rowsN, 1)))), [
                    s.set_var("dy", -1),
                    s.repeat(3, [
                        s.set_var("dx", -1),
                        s.repeat(3, [
                            s.if_(s.lnot(s.land(s.eq(dx, 0), s.eq(dy, 0))), [
                                s.set_var("nIdx", s.add(pIdx, s.add(s.mul(dy, colsN), dx))),
                                s.set_var("nR", s.item_of(accR, nIdx)),
                                s.set_var("nG", s.item_of(accG, nIdx)),
                                s.set_var("nB", s.item_of(accB, nIdx)),
                                # Squared color distance
                                s.set_var("dCol", s.add(
                                    s.mul(s.sub(nR, cR), s.sub(nR, cR)),
                                    s.add(s.mul(s.sub(nG, cG), s.sub(nG, cG)), s.mul(s.sub(nB, cB), s.sub(nB, cB))),
                                )),
                                # Edge-stopping weight: 1 / (1 + dCol * 28.0) -> crisp edges, smooth flat walls!
                                s.set_var("nW", s.div(1.0, s.add(1.0, s.mul(dCol, 28.0)))),
                                s.change_var("sR", s.mul(nR, nW)),
                                s.change_var("sG", s.mul(nG, nW)),
                                s.change_var("sB", s.mul(nB, nW)),
                                s.change_var("wSum", nW),
                            ]),
                            s.change_var("dx", 1),
                        ]),
                        s.change_var("dy", 1),
                    ]),
                ]),
                s.set_var("invL", s.div(255.0, wSum)),
                s.set_var("bayer", s.sub(s.mul(s.add(s.mul(s.mod(px, 2), 2), s.mod(py, 2)), 0.25), 0.375)),
                s.set_var("pR", s.floor(s.add(s.mul(sR, invL), bayer))),
                s.set_var("pG", s.floor(s.add(s.mul(sG, invL), bayer))),
                s.set_var("pB", s.floor(s.add(s.mul(sB, invL), bayer))),
                *clamp_stmts(s, "pR", 0, 255), *clamp_stmts(s, "pG", 0, 255), *clamp_stmts(s, "pB", 0, 255),
                s.set_var("outCol", s.add(s.mul(pR, 65536), s.add(s.mul(pG, 256), pB))),
                s.pen_set_color(outCol),
                s.if_(s.eq(px, 0), [s.pen_down()]),
                s.change_x(PIXEL_STEP),
                s.change_var("px", 1),
                s.change_var("pIdx", 1),
            ]),
            s.pen_up(),
            s.change_var("py", 1),
        ]),
        s.set_var("DENOISE_MS", s.sub(now_ms(), tD0)),
    ])

    p_one_spp = s.define_proc("trace_one_spp", warp=True, body=[
        s.set_var("py", 0),
        s.repeat(rowsN, [
            s.call_proc(p_pass_row, py),
            s.change_var("py", 1),
        ]),
    ])

    p_run_all = s.define_proc("run_pathtracer", warp=False, body=[
        s.set_var("t0", now_ms()),
        s.call_proc(p_init_buf),
        s.set_var("spp", 1),
        s.repeat(TARGET_SPP, [
            s.set_var("invSpp", s.div(1.0, spp)),
            s.set_var("alphaByte", s.round_(s.div(255.0, spp))),
            s.if_(s.lt(alphaByte, 1), [s.set_var("alphaByte", 1)]),
            s.if_(s.gt(alphaByte, 255), [s.set_var("alphaByte", 255)]),
            s.call_proc(p_one_spp),
            s.set_var("SPP_DONE", spp),
            s.change_var("spp", 1),
        ]),
        s.if_(s.land(s.eq(ACCUM_MODE, 0), s.eq(DENOISE, 1)), [
            s.call_proc(p_denoise),
        ]),
        s.set_var("TOTAL_MS", s.sub(now_ms(), t0)),
        s.set_var("MS_PER_SPP", s.div(TOTAL_MS, TARGET_SPP)),
    ])

    s.when_flag_clicked([
        s.hide(),
        s.set_var("DONE", 0),
        s.call_proc(p_run_all),
        s.set_var("DONE", 1),
    ])

    from pathlib import Path
    out = pb.save_sb3(Path(__file__).resolve().parent / "sb3" / "ue5_pathtracer.sb3")
    print("Built:", out, f"({len(s.blocks)} Scratch blocks)")


if __name__ == "__main__":
    build_pathtracer()
