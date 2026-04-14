/**
 * EthicTech Landing Page JavaScript
 * Scroll animations, language toggle, terminal animation, smoke effect
 */
(function () {
    'use strict';

    // -----------------------------------------------------------------------
    // Scroll-triggered Animations (IntersectionObserver)
    // -----------------------------------------------------------------------
    const animObserver = new IntersectionObserver(
        (entries) => {
            entries.forEach((entry) => {
                if (entry.isIntersecting) {
                    const delay = parseInt(entry.target.dataset.delay || '0', 10);
                    setTimeout(() => entry.target.classList.add('visible'), delay);
                    animObserver.unobserve(entry.target);
                }
            });
        },
        { threshold: 0.08, rootMargin: '0px 0px -40px 0px' }
    );

    document.querySelectorAll('[data-animate]').forEach((el) => animObserver.observe(el));

    // -----------------------------------------------------------------------
    // Language Toggle (EN / HE)
    // -----------------------------------------------------------------------
    const langToggle = document.getElementById('lang-toggle');
    let currentLang = localStorage.getItem('ec-lang') || 'en';

    function setLanguage(lang) {
        currentLang = lang;
        document.documentElement.lang = lang;
        document.documentElement.dir = lang === 'he' ? 'rtl' : 'ltr';

        document.querySelectorAll('[data-en][data-he]').forEach((el) => {
            el.textContent = el.dataset[lang];
        });

        if (langToggle) {
            langToggle.textContent = lang === 'en' ? 'EN / HE' : 'HE / EN';
        }

        localStorage.setItem('ec-lang', lang);
    }

    setLanguage(currentLang);

    if (langToggle) {
        langToggle.addEventListener('click', () => {
            setLanguage(currentLang === 'en' ? 'he' : 'en');
        });
    }

    // -----------------------------------------------------------------------
    // Terminal Typing Animation
    // -----------------------------------------------------------------------
    const terminalEl = document.getElementById('terminal-animation');

    const terminalLines = [
        { text: '> Parsing Council HTML export...', cls: 'text-[#a3a3a3]', delay: 400 },
        { text: '  Extracted 12 sections, 3 experiments', cls: 'text-[#e5e5e5]', delay: 500 },
        { text: '', cls: '', delay: 200 },
        { text: '> Running 42 law-compliance checks...', cls: 'text-[#a3a3a3]', delay: 400 },
        { text: '  \u2714 38 passed', cls: 'text-[#22c55e]', delay: 350 },
        { text: '  \u2718 2 errors found', cls: 'text-[#ef4444]', delay: 350 },
        { text: '  \u26A0 2 warnings found', cls: 'text-[#f59e0b]', delay: 350 },
        { text: '', cls: '', delay: 200 },
        { text: '> AI reviewing 11 ethical themes...', cls: 'text-[#a3a3a3]', delay: 500 },
        { text: '  [3Rs & Alternatives]      3/3 Adequate', cls: 'text-[#22c55e]', delay: 600 },
        { text: '  [Euthanasia & Endpoints]  1/3 Inadequate', cls: 'text-[#ef4444]', delay: 600 },
        { text: '  [Severity & Monitoring]   2/3 Partial', cls: 'text-[#f59e0b]', delay: 600 },
        { text: '  [Harm-Benefit]            3/3 Adequate', cls: 'text-[#22c55e]', delay: 600 },
        { text: '  ...processing 7 more themes', cls: 'text-[#737373]', delay: 400 },
        { text: '', cls: '', delay: 200 },
        { text: '> Report ready. 2 critical issues flagged.', cls: 'text-[#22c55e] font-semibold', delay: 500 },
    ];

    function runTerminalAnimation() {
        if (!terminalEl) return;
        terminalEl.innerHTML = '';

        let totalDelay = 800; // initial pause

        terminalLines.forEach((line) => {
            totalDelay += line.delay;
            setTimeout(() => {
                const div = document.createElement('div');
                div.className = line.cls + ' font-mono';
                div.style.opacity = '0';
                div.style.transform = 'translateY(4px)';
                div.style.transition = 'opacity 0.3s ease, transform 0.3s ease';

                if (line.text === '') {
                    div.innerHTML = '&nbsp;';
                } else {
                    div.textContent = line.text;
                }

                terminalEl.appendChild(div);

                // Fade in
                requestAnimationFrame(() => {
                    div.style.opacity = '1';
                    div.style.transform = 'translateY(0)';
                });

                // Auto-scroll
                terminalEl.scrollTop = terminalEl.scrollHeight;
            }, totalDelay);
        });

        // Add blinking cursor at the end
        totalDelay += 400;
        setTimeout(() => {
            const cursor = document.createElement('span');
            cursor.className = 'terminal-cursor';
            terminalEl.appendChild(cursor);
        }, totalDelay);

        // Loop the animation
        const loopDelay = totalDelay + 5000;
        setTimeout(runTerminalAnimation, loopDelay);
    }

    runTerminalAnimation();

    // -----------------------------------------------------------------------
    // Smoke / Particle Effect (adapted from template, dark green theme)
    // -----------------------------------------------------------------------
    const smokeLayer = document.getElementById('smoke-layer');

    if (smokeLayer) {
        const glyphs = ['\u00B7\u00B7', '\u00B7\u00B7\u00B7', '\u00B0\u00B0', '\u2219\u2219\u2219', '~~', '\u2591\u2591', '\u02D9\u02D9', '\u22C5\u22C5\u22C5'];
        let lastX = window.innerWidth / 2;
        let lastY = window.innerHeight / 2;
        let lastEmit = 0;

        function emitSmoke(x, y, intensity) {
            intensity = intensity || 1;
            const count = Math.max(1, Math.min(2, Math.round(intensity)));

            for (let i = 0; i < count; i++) {
                const node = document.createElement('span');
                node.className = 'smoke-char';
                node.textContent = glyphs[Math.floor(Math.random() * glyphs.length)];

                const offsetX = (Math.random() - 0.5) * 26;
                const offsetY = (Math.random() - 0.5) * 16;
                const driftX = (Math.random() - 0.5) * 100;
                const driftY = -80 - Math.random() * 100;
                const scale = 0.95 + Math.random() * 1.1;
                const duration = 1600 + Math.random() * 1200;
                const rotation = (Math.random() - 0.5) * 14;
                const rotateEnd = ((Math.random() - 0.5) * 26) + 'deg';

                node.style.left = (x + offsetX) + 'px';
                node.style.top = (y + offsetY) + 'px';
                node.style.setProperty('--drift-x', driftX + 'px');
                node.style.setProperty('--drift-y', driftY + 'px');
                node.style.setProperty('--rotate-end', rotateEnd);
                node.style.fontSize = (20 + Math.random() * 18) + 'px';
                node.style.opacity = (0.06 + Math.random() * 0.1) + '';
                node.style.transform = 'translate3d(0,0,0) scale(' + scale + ') rotate(' + rotation + 'deg)';
                node.style.animationDuration = duration + 'ms';

                smokeLayer.appendChild(node);
                node.addEventListener('animationend', function () { node.remove(); }, { once: true });
            }
        }

        window.addEventListener('mousemove', function (event) {
            var now = performance.now();
            var dx = event.clientX - lastX;
            var dy = event.clientY - lastY;
            var speed = Math.hypot(dx, dy);

            if (now - lastEmit > 32) {
                emitSmoke(event.clientX, event.clientY, speed / 30);
                lastEmit = now;
                lastX = event.clientX;
                lastY = event.clientY;
            }
        }, { passive: true });

        window.addEventListener('touchmove', function (event) {
            var touch = event.touches[0];
            if (!touch) return;
            emitSmoke(touch.clientX, touch.clientY, 1);
        }, { passive: true });
    }
})();
