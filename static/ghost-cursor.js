// UniTrack lightweight GhostCursor-style trail.
// Uses Canvas 2D instead of React Bits' Three.js bloom/post-processing stack
// so it stays smooth on high-refresh-rate displays.

const host = document.getElementById("ghost-cursor-root");

if (
    host &&
    !window.matchMedia("(prefers-reduced-motion: reduce)").matches &&
    !window.matchMedia("(pointer: coarse)").matches
) {
    const config = {
        color: "#6657FF",
        trailLength: 50,
        inertia: 0.5,
        fadeDelayMs: 1000,
        fadeDurationMs: 1500,
        renderScale: 0.72
    };

    const canvas = document.createElement("canvas");
    canvas.setAttribute("aria-hidden", "true");
    host.appendChild(canvas);

    const ctx = canvas.getContext("2d", {
        alpha: true,
        desynchronized: true
    });

    const trail = Array.from(
        { length: config.trailLength },
        () => ({ x: 0, y: 0 })
    );

    const pointer = { x: 0, y: 0 };

    let hasPointer = false;
    let lastMoveTime = 0;
    let rafId = null;
    let running = false;
    let width = 0;
    let height = 0;
    let pixelRatio = 1;

    function hexToRgb(hex) {
        const clean = hex.replace("#", "");
        const value = parseInt(clean, 16);

        return {
            r: (value >> 16) & 255,
            g: (value >> 8) & 255,
            b: value & 255
        };
    }

    const rgb = hexToRgb(config.color);

    // Pre-render one soft glow and reuse it every frame.
    // drawImage is far cheaper than rebuilding radial gradients 50 times/frame.
    const spriteSize = 220;
    const sprite = document.createElement("canvas");
    sprite.width = spriteSize;
    sprite.height = spriteSize;

    const spriteCtx = sprite.getContext("2d");
    const radius = spriteSize / 2;

    const glow = spriteCtx.createRadialGradient(
        radius,
        radius,
        0,
        radius,
        radius,
        radius
    );

    glow.addColorStop(
        0,
        `rgba(${rgb.r}, ${rgb.g}, ${rgb.b}, 0.52)`
    );
    glow.addColorStop(
        0.28,
        `rgba(${rgb.r}, ${rgb.g}, ${rgb.b}, 0.32)`
    );
    glow.addColorStop(
        0.62,
        `rgba(${rgb.r}, ${rgb.g}, ${rgb.b}, 0.12)`
    );
    glow.addColorStop(1, "rgba(180, 151, 207, 0)");

    spriteCtx.fillStyle = glow;
    spriteCtx.fillRect(0, 0, spriteSize, spriteSize);

    function resize() {
        width = window.innerWidth;
        height = window.innerHeight;

        // A slightly sub-native backing resolution is intentional.
        // The effect is blurred anyway, and this keeps it very cheap.
        pixelRatio = Math.max(
            0.6,
            Math.min(window.devicePixelRatio || 1, 1) * config.renderScale
        );

        canvas.width = Math.max(1, Math.floor(width * pixelRatio));
        canvas.height = Math.max(1, Math.floor(height * pixelRatio));

        canvas.style.width = `${width}px`;
        canvas.style.height = `${height}px`;

        ctx.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
    }

    function startLoop() {
        if (running) {
            return;
        }

        running = true;
        rafId = requestAnimationFrame(animate);
    }

    function onPointerMove(event) {
        pointer.x = event.clientX;
        pointer.y = event.clientY;
        lastMoveTime = performance.now();

        // First movement initializes the whole trail at the cursor.
        // This removes the old random blob appearing from the centre.
        if (!hasPointer) {
            hasPointer = true;

            trail.forEach(point => {
                point.x = pointer.x;
                point.y = pointer.y;
            });
        }

        startLoop();
    }

    function animate(now) {
        if (!hasPointer || document.hidden) {
            running = false;
            rafId = null;
            return;
        }

        const idleTime = now - lastMoveTime;

        let opacity = 1;

        if (idleTime > config.fadeDelayMs) {
            opacity = 1 - Math.min(
                1,
                (idleTime - config.fadeDelayMs) /
                config.fadeDurationMs
            );
        }

        // Inertia 0.5 -> responsive but still visibly floaty.
        const headFollow = 0.20 + (1 - config.inertia) * 0.30;

        trail[0].x += (pointer.x - trail[0].x) * headFollow;
        trail[0].y += (pointer.y - trail[0].y) * headFollow;

        for (let i = 1; i < trail.length; i++) {
            const follow = 0.22;

            trail[i].x +=
                (trail[i - 1].x - trail[i].x) * follow;

            trail[i].y +=
                (trail[i - 1].y - trail[i].y) * follow;
        }

        ctx.clearRect(0, 0, width, height);
        ctx.globalCompositeOperation = "lighter";

        // Render every second trail point. We still maintain 50 points for
        // motion quality, but only make ~25 very cheap sprite draw calls.
        for (let i = trail.length - 1; i >= 0; i -= 2) {
            const t = 1 - i / trail.length;
            const strength = t * t;
            const size = 70 + strength * 165;
            const point = trail[i];

            ctx.globalAlpha = opacity * strength * 0.48;

            ctx.drawImage(
                sprite,
                point.x - size / 2,
                point.y - size / 2,
                size,
                size
            );
        }

        ctx.globalAlpha = 1;
        ctx.globalCompositeOperation = "source-over";

        if (opacity <= 0.001) {
            ctx.clearRect(0, 0, width, height);
            running = false;
            rafId = null;
            return;
        }

        rafId = requestAnimationFrame(animate);
    }

    function onVisibilityChange() {
        if (document.hidden) {
            if (rafId) {
                cancelAnimationFrame(rafId);
            }

            rafId = null;
            running = false;
        } else if (hasPointer) {
            startLoop();
        }
    }

    resize();

    window.addEventListener("resize", resize, { passive: true });
    window.addEventListener("pointermove", onPointerMove, { passive: true });
    document.addEventListener("visibilitychange", onVisibilityChange);
}
