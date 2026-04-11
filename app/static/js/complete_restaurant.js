(function () {
    const form = document.getElementById("restaurantForm");
    const restaurantImageInput = document.getElementById("anhNhaHang");
    const restaurantImageName = document.getElementById("anhNhaHangName");
    const restaurantImagePreview = document.getElementById("restaurantImagePreview");
    const restaurantImageEmpty = document.getElementById("restaurantImageEmpty");

    if (!form || !restaurantImageInput || !restaurantImageName || !restaurantImagePreview || !restaurantImageEmpty) {
        return;
    }

    const currentRestaurantImage = form.dataset.restaurantImageUrl || "";
    const currentImageName = form.dataset.restaurantImageName || "Chưa có file nào được chọn";

    let restaurantImageObjectUrl = "";

    function revokeRestaurantObjectUrl() {
        if (restaurantImageObjectUrl) {
            URL.revokeObjectURL(restaurantImageObjectUrl);
            restaurantImageObjectUrl = "";
        }
    }

    function syncRestaurantPreview() {
        const selectedFile = restaurantImageInput.files && restaurantImageInput.files.length
            ? restaurantImageInput.files[0]
            : null;

        if (!selectedFile) {
            revokeRestaurantObjectUrl();
            if (currentRestaurantImage) {
                restaurantImagePreview.src = currentRestaurantImage;
                restaurantImagePreview.style.display = "block";
                restaurantImageEmpty.style.display = "none";
            } else {
                restaurantImagePreview.style.display = "none";
                restaurantImagePreview.removeAttribute("src");
                restaurantImageEmpty.style.display = "flex";
            }
            return;
        }

        revokeRestaurantObjectUrl();
        restaurantImageObjectUrl = URL.createObjectURL(selectedFile);
        restaurantImagePreview.src = restaurantImageObjectUrl;
        restaurantImagePreview.style.display = "block";
        restaurantImageEmpty.style.display = "none";
    }

    restaurantImageInput.addEventListener("change", function () {
        const selectedFile = this.files && this.files.length ? this.files[0] : null;
        restaurantImageName.textContent = selectedFile ? selectedFile.name : currentImageName;
        syncRestaurantPreview();
    });

    syncRestaurantPreview();
})();
