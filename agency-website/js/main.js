/* ========================================
   NALLYMAKES — Main JavaScript
   Lively Edition
   ======================================== */

(function () {
    'use strict';

    // ---- Page Loader ----
    window.addEventListener('load', function () {
        var loader = document.getElementById('pageLoader');
        if (loader) {
            setTimeout(function () { loader.classList.add('hidden'); }, 400);
        }
    });

    // ---- Navbar Scroll ----
    var navbar = document.getElementById('navbar');
    var lastScroll = 0;
    window.addEventListener('scroll', function () {
        var st = window.scrollY;
        if (st > 80) {
            navbar.classList.add('scrolled');
        } else {
            navbar.classList.remove('scrolled');
        }
        lastScroll = st;
    });

    // ---- Hamburger Menu ----
    var hamburger = document.getElementById('hamburger');
    var navLinks = document.getElementById('navLinks');
    if (hamburger && navLinks) {
        hamburger.addEventListener('click', function () {
            hamburger.classList.toggle('active');
            navLinks.classList.toggle('active');
        });
        // Close menu on link click
        navLinks.querySelectorAll('a').forEach(function (link) {
            link.addEventListener('click', function () {
                hamburger.classList.remove('active');
                navLinks.classList.remove('active');
            });
        });
    }

    // ---- Typing Effect ----
    var typingEl = document.getElementById('heroTyping');
    if (typingEl) {
        var phrases = [
            'digital products',
            'websites that convert',
            'AI-powered tools',
            'apps that scale',
            'brands that stand out'
        ];
        var phraseIdx = 0;
        var charIdx = 0;
        var isDeleting = false;
        var typeSpeed = 80;

        function typeLoop() {
            var current = phrases[phraseIdx];
            if (isDeleting) {
                typingEl.textContent = current.substring(0, charIdx - 1);
                charIdx--;
                typeSpeed = 40;
            } else {
                typingEl.textContent = current.substring(0, charIdx + 1);
                charIdx++;
                typeSpeed = 80;
            }

            if (!isDeleting && charIdx === current.length) {
                typeSpeed = 2000; // pause at end
                isDeleting = true;
            } else if (isDeleting && charIdx === 0) {
                isDeleting = false;
                phraseIdx = (phraseIdx + 1) % phrases.length;
                typeSpeed = 400; // pause before next word
            }

            setTimeout(typeLoop, typeSpeed);
        }
        setTimeout(typeLoop, 1200);
    }

    // ---- Particle System ----
    var canvas = document.getElementById('particles');
    if (canvas) {
        var ctx = canvas.getContext('2d');
        var particles = [];
        var particleCount = 60;

        function resizeCanvas() {
            canvas.width = canvas.parentElement.offsetWidth;
            canvas.height = canvas.parentElement.offsetHeight;
        }
        resizeCanvas();
        window.addEventListener('resize', resizeCanvas);

        function Particle() {
            this.x = Math.random() * canvas.width;
            this.y = Math.random() * canvas.height;
            this.size = Math.random() * 2 + 0.5;
            this.speedX = (Math.random() - 0.5) * 0.5;
            this.speedY = (Math.random() - 0.5) * 0.5;
            this.opacity = Math.random() * 0.5 + 0.1;
        }

        Particle.prototype.update = function () {
            this.x += this.speedX;
            this.y += this.speedY;
            if (this.x < 0 || this.x > canvas.width) this.speedX *= -1;
            if (this.y < 0 || this.y > canvas.height) this.speedY *= -1;
        };

        Particle.prototype.draw = function () {
            ctx.beginPath();
            ctx.arc(this.x, this.y, this.size, 0, Math.PI * 2);
            ctx.fillStyle = 'rgba(108, 92, 231, ' + this.opacity + ')';
            ctx.fill();
        };

        for (var i = 0; i < particleCount; i++) {
            particles.push(new Particle());
        }

        function connectParticles() {
            for (var a = 0; a < particles.length; a++) {
                for (var b = a + 1; b < particles.length; b++) {
                    var dx = particles[a].x - particles[b].x;
                    var dy = particles[a].y - particles[b].y;
                    var dist = Math.sqrt(dx * dx + dy * dy);
                    if (dist < 120) {
                        var opacity = (1 - dist / 120) * 0.15;
                        ctx.beginPath();
                        ctx.strokeStyle = 'rgba(108, 92, 231, ' + opacity + ')';
                        ctx.lineWidth = 0.5;
                        ctx.moveTo(particles[a].x, particles[a].y);
                        ctx.lineTo(particles[b].x, particles[b].y);
                        ctx.stroke();
                    }
                }
            }
        }

        function animateParticles() {
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            for (var i = 0; i < particles.length; i++) {
                particles[i].update();
                particles[i].draw();
            }
            connectParticles();
            requestAnimationFrame(animateParticles);
        }
        animateParticles();
    }

    // ---- Scroll Reveal ----
    var revealElements = document.querySelectorAll('[data-reveal]');
    if (revealElements.length > 0) {
        var revealObserver = new IntersectionObserver(function (entries) {
            entries.forEach(function (entry) {
                if (entry.isIntersecting) {
                    entry.target.classList.add('revealed');
                }
            });
        }, { threshold: 0.15, rootMargin: '0px 0px -40px 0px' });

        revealElements.forEach(function (el) {
            revealObserver.observe(el);
        });
    }

    // ---- Counter Animation ----
    var counters = document.querySelectorAll('.count-up');
    var counterDone = false;
    if (counters.length > 0) {
        var counterObserver = new IntersectionObserver(function (entries) {
            entries.forEach(function (entry) {
                if (entry.isIntersecting && !counterDone) {
                    counterDone = true;
                    counters.forEach(function (counter) {
                        var target = parseInt(counter.getAttribute('data-target'));
                        var duration = 2000;
                        var start = 0;
                        var startTime = null;

                        function easeOutQuart(t) {
                            return 1 - Math.pow(1 - t, 4);
                        }

                        function animate(timestamp) {
                            if (!startTime) startTime = timestamp;
                            var progress = Math.min((timestamp - startTime) / duration, 1);
                            var easedProgress = easeOutQuart(progress);
                            var current = Math.floor(easedProgress * target);
                            counter.textContent = current + (target >= 99 ? '%' : '+');
                            if (progress < 1) {
                                requestAnimationFrame(animate);
                            } else {
                                counter.textContent = target + (target >= 99 ? '%' : '+');
                            }
                        }
                        requestAnimationFrame(animate);
                    });
                }
            });
        }, { threshold: 0.5 });

        counters.forEach(function (c) { counterObserver.observe(c); });
    }

    // ---- 3D Card Tilt ----
    var tiltCards = document.querySelectorAll('.tilt-card');
    tiltCards.forEach(function (card) {
        card.addEventListener('mousemove', function (e) {
            var rect = card.getBoundingClientRect();
            var x = e.clientX - rect.left;
            var y = e.clientY - rect.top;
            var centerX = rect.width / 2;
            var centerY = rect.height / 2;
            var rotateX = ((y - centerY) / centerY) * -8;
            var rotateY = ((x - centerX) / centerX) * 8;

            card.style.transform = 'perspective(1000px) rotateX(' + rotateX + 'deg) rotateY(' + rotateY + 'deg) translateY(-6px)';
        });

        card.addEventListener('mouseleave', function () {
            card.style.transform = 'perspective(1000px) rotateX(0) rotateY(0) translateY(0)';
            card.style.transition = 'transform 0.4s ease';
        });

        card.addEventListener('mouseenter', function () {
            card.style.transition = 'transform 0.1s ease';
        });
    });

    // ---- Button Ripple Effect ----
    var rippleBtns = document.querySelectorAll('.ripple-btn');
    rippleBtns.forEach(function (btn) {
        btn.addEventListener('click', function (e) {
            var rect = btn.getBoundingClientRect();
            var x = e.clientX - rect.left;
            var y = e.clientY - rect.top;
            var circle = document.createElement('span');
            circle.classList.add('ripple-circle');
            circle.style.left = x + 'px';
            circle.style.top = y + 'px';
            var size = Math.max(rect.width, rect.height);
            circle.style.width = circle.style.height = size + 'px';
            circle.style.marginLeft = (-size / 2) + 'px';
            circle.style.marginTop = (-size / 2) + 'px';
            btn.appendChild(circle);
            setTimeout(function () { circle.remove(); }, 600);
        });
    });

    // ---- Testimonial Carousel ----
    var track = document.getElementById('testimonialTrack');
    var prevBtn = document.getElementById('prevBtn');
    var nextBtn = document.getElementById('nextBtn');
    var dotsContainer = document.getElementById('carouselDots');

    if (track && prevBtn && nextBtn && dotsContainer) {
        var slides = track.querySelectorAll('.testimonial-card');
        var currentIndex = 0;
        var slidesVisible = getSlidesVisible();
        var maxIndex = Math.max(0, slides.length - slidesVisible);
        var autoPlayTimer;

        function getSlidesVisible() {
            if (window.innerWidth <= 768) return 1;
            if (window.innerWidth <= 1024) return 2;
            return 3;
        }

        function buildDots() {
            dotsContainer.innerHTML = '';
            var dotCount = maxIndex + 1;
            for (var d = 0; d < dotCount; d++) {
                var dot = document.createElement('span');
                dot.classList.add('carousel-dot');
                if (d === currentIndex) dot.classList.add('active');
                dot.setAttribute('data-index', d);
                dot.addEventListener('click', function () {
                    currentIndex = parseInt(this.getAttribute('data-index'));
                    updateCarousel();
                });
                dotsContainer.appendChild(dot);
            }
        }

        function updateCarousel() {
            if (currentIndex > maxIndex) currentIndex = maxIndex;
            if (currentIndex < 0) currentIndex = 0;
            var slideWidth = slides[0].offsetWidth + 24; // gap
            track.style.transform = 'translateX(-' + (currentIndex * slideWidth) + 'px)';
            // Update dots
            var dots = dotsContainer.querySelectorAll('.carousel-dot');
            dots.forEach(function (dot, idx) {
                dot.classList.toggle('active', idx === currentIndex);
            });
        }

        prevBtn.addEventListener('click', function () {
            currentIndex--;
            if (currentIndex < 0) currentIndex = maxIndex;
            updateCarousel();
            resetAutoPlay();
        });

        nextBtn.addEventListener('click', function () {
            currentIndex++;
            if (currentIndex > maxIndex) currentIndex = 0;
            updateCarousel();
            resetAutoPlay();
        });

        function startAutoPlay() {
            autoPlayTimer = setInterval(function () {
                currentIndex++;
                if (currentIndex > maxIndex) currentIndex = 0;
                updateCarousel();
            }, 4000);
        }

        function resetAutoPlay() {
            clearInterval(autoPlayTimer);
            startAutoPlay();
        }

        window.addEventListener('resize', function () {
            slidesVisible = getSlidesVisible();
            maxIndex = Math.max(0, slides.length - slidesVisible);
            buildDots();
            updateCarousel();
        });

        buildDots();
        startAutoPlay();
    }

    // ---- Contact Form ----
    var form = document.getElementById('contactForm');
    var formStatus = document.getElementById('formStatus');
    if (form) {
        form.addEventListener('submit', function (e) {
            e.preventDefault();
            var name = form.querySelector('#name').value.trim();
            var email = form.querySelector('#email').value.trim();
            var service = form.querySelector('#service').value;
            var message = form.querySelector('#message').value.trim();

            if (!name || !email || !service || !message) {
                formStatus.className = 'form-status error';
                formStatus.textContent = 'Please fill in all required fields.';
                return;
            }

            // Mailto fallback
            var subject = encodeURIComponent('Project Inquiry from ' + name + ' — ' + service);
            var body = encodeURIComponent(
                'Name: ' + name + '\n' +
                'Email: ' + email + '\n' +
                'Service: ' + service + '\n' +
                'Budget: ' + (form.querySelector('#budget').value || 'Not specified') + '\n\n' +
                'Message:\n' + message
            );
            window.location.href = 'mailto:hello@nallymakes.com?subject=' + subject + '&body=' + body;

            formStatus.className = 'form-status success';
            formStatus.textContent = 'Opening your email client... If it doesn\'t open, email us at hello@nallymakes.com';
            form.reset();

            setTimeout(function () {
                formStatus.className = 'form-status';
                formStatus.textContent = '';
            }, 5000);
        });
    }

    // ---- Smooth Scroll for Anchor Links ----
    document.querySelectorAll('a[href^="#"]').forEach(function (anchor) {
        anchor.addEventListener('click', function (e) {
            e.preventDefault();
            var target = document.querySelector(this.getAttribute('href'));
            if (target) {
                var offset = 80; // navbar height
                var top = target.getBoundingClientRect().top + window.pageYOffset - offset;
                window.scrollTo({ top: top, behavior: 'smooth' });
            }
        });
    });

})();
