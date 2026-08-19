const themeButton =
    document.getElementById("themeToggle");


if (localStorage.getItem("theme") === "dark") {

    document.body.classList.add("dark-mode");

    if (themeButton) {

        themeButton.innerText = "☀️";

    }

}


if (themeButton) {

    themeButton.addEventListener("click", function () {

        document.body.classList.toggle("dark-mode");


        if (
            document.body.classList.contains("dark-mode")
        ) {

            localStorage.setItem("theme", "dark");

            themeButton.innerText = "☀️";

        } else {

            localStorage.setItem("theme", "light");

            themeButton.innerText = "🌙";

        }

    });

}