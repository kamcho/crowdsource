(function () {
    var carousel = document.querySelector('[data-hero-carousel]');
    if (!carousel) {
        return;
    }

    var track = carousel.querySelector('[data-hero-carousel-track]');
    var slides = carousel.querySelectorAll('[data-hero-carousel-slide]');
    var dots = carousel.querySelectorAll('[data-hero-carousel-dot]');
    if (!track || slides.length <= 1) {
        return;
    }

    var index = 0;
    var intervalMs = parseInt(carousel.getAttribute('data-interval') || '3000', 10);
    var timerId = null;

    function goTo(nextIndex) {
        index = (nextIndex + slides.length) % slides.length;
        track.style.transform = 'translateX(-' + (index * 100) + '%)';

        dots.forEach(function (dot, dotIndex) {
            var isActive = dotIndex === index;
            dot.classList.toggle('is-active', isActive);
            dot.setAttribute('aria-selected', isActive ? 'true' : 'false');
        });
    }

    function startTimer() {
        stopTimer();
        timerId = window.setInterval(function () {
            goTo(index + 1);
        }, intervalMs);
    }

    function stopTimer() {
        if (timerId !== null) {
            window.clearInterval(timerId);
            timerId = null;
        }
    }

    dots.forEach(function (dot, dotIndex) {
        dot.addEventListener('click', function () {
            goTo(dotIndex);
            startTimer();
        });
    });

    carousel.addEventListener('mouseenter', stopTimer);
    carousel.addEventListener('mouseleave', startTimer);
    carousel.addEventListener('focusin', stopTimer);
    carousel.addEventListener('focusout', startTimer);

    goTo(0);
    startTimer();
})();
