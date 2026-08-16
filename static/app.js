document.querySelectorAll(".tag-click").forEach((tag) => {
    tag.addEventListener("click", () => {
        document.querySelectorAll(".tag-click").forEach((item) => {
            item.classList.remove("selected-tag");
        });

        tag.classList.add("selected-tag");
        document.getElementById("selected-tag-path").value = tag.dataset.path;
        document.getElementById("selected-tag-id").value = tag.dataset.tagid || "";
    });
});
