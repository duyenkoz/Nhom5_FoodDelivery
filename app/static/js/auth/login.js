(function () {
    const pageDataElement = document.getElementById("login-page-data");
    let pageData = {};

    if (pageDataElement) {
        try {
            pageData = JSON.parse(pageDataElement.textContent || "{}") || {};
        } catch (_error) {
            pageData = {};
        }
    }

    const loginForm = document.getElementById("loginForm");
    const identifierInput = document.getElementById("identifier");
    const passwordInput = document.getElementById("password");
    const rememberMeInput = document.getElementById("rememberMe");
    const passwordToggle = document.getElementById("passwordToggle");
    const passwordEye = document.getElementById("passwordEye");
    const loginSubmitBtn = document.getElementById("loginSubmitBtn");
    const googleLoginBtn = document.getElementById("googleLoginBtn");
    const facebookLoginBtn = document.getElementById("facebookLoginBtn");
    const forgotPasswordBtn = document.getElementById("forgotPasswordBtn");
    const forgotPasswordModal = document.getElementById("forgotPasswordModal");
    const forgotPasswordClose = document.getElementById("forgotPasswordClose");
    const forgotLookupCloseBtn = document.getElementById("forgotLookupCloseBtn");
    const forgotLookupBtn = document.getElementById("forgotLookupBtn");
    const forgotBackBtn = document.getElementById("forgotBackBtn");
    const forgotVerifyBtn = document.getElementById("forgotVerifyBtn");
    const forgotResendBtn = document.getElementById("forgotResendBtn");
    const forgotVerifyCloseBtn = document.getElementById("forgotVerifyCloseBtn");
    const forgotResetBtn = document.getElementById("forgotResetBtn");
    const forgotResetCloseBtn = document.getElementById("forgotResetCloseBtn");
    const forgotEmailInput = document.getElementById("forgotEmail");
    const forgotOtpInput = document.getElementById("forgotOtp");
    const forgotNewPasswordInput = document.getElementById("forgotNewPassword");
    const forgotNewPasswordToggle = document.getElementById("forgotNewPasswordToggle");
    const forgotNewPasswordEye = document.getElementById("forgotNewPasswordEye");
    const forgotConfirmPasswordInput = document.getElementById("forgotConfirmPassword");
    const forgotConfirmPasswordToggle = document.getElementById("forgotConfirmPasswordToggle");
    const forgotConfirmPasswordEye = document.getElementById("forgotConfirmPasswordEye");
    const forgotLookupMessage = document.getElementById("forgotLookupMessage");
    const forgotVerifyMessage = document.getElementById("forgotVerifyMessage");
    const forgotResetMessage = document.getElementById("forgotResetMessage");
    const forgotStepLookup = document.getElementById("forgotStepLookup");
    const forgotStepVerify = document.getElementById("forgotStepVerify");
    const forgotStepReset = document.getElementById("forgotStepReset");
    const googlePhoneModal = document.getElementById("googlePhoneModal");
    const googlePhoneClose = document.getElementById("googlePhoneClose");
    const googlePhoneDismiss = document.getElementById("googlePhoneDismiss");
    const googlePhoneSubmit = document.getElementById("googlePhoneSubmit");
    const googlePhoneInput = document.getElementById("googlePhoneInput");
    const googlePhoneMessage = document.getElementById("googlePhoneMessage");
    const googlePhoneNote = document.getElementById("googlePhoneNote");

    const loginStorageKey = "fivefood_login_identifier";
    const loginRememberKey = "fivefood_login_remember";
    const registerUrl = pageData.registerUrl || "/register";
    const hasServerErrors = Boolean(pageData.hasServerErrors);
    const googleAccountLookupUrl = pageData.googleAccountLookupUrl || "/check-google-account";
    const googleAccountMessage = pageData.googleAccountMessage || "Tài khoản này đăng nhập bằng Google. Vui lòng đăng nhập bằng Google.";
    const googleLoginUrl = pageData.googleLoginUrl || "/google-login";
    const googlePhoneSubmitUrl = pageData.googlePhoneSubmitUrl || "/google-phone";
    const googlePhonePending = Boolean(pageData.googlePhonePending);
    const googlePhonePendingName = pageData.googlePhonePendingName || "";
    const googlePhonePendingEmail = pageData.googlePhonePendingEmail || "";
    const forgotLookupUrl = pageData.forgotLookupUrl || "/forgot-password";
    const forgotVerifyUrl = pageData.forgotVerifyUrl || "/verify-otp";
    const forgotResendUrl = pageData.forgotResendUrl || "/resend-otp";
    const forgotResetUrl = pageData.forgotResetUrl || "/reset-password";

    let forgotState = {
        email: "",
        resendCooldown: 0,
        resendTimerId: null,
        resendAvailableAt: null,
    };

    let googleAccountLookupSeq = 0;

    function on(element, eventName, handler) {
        if (element) {
            element.addEventListener(eventName, handler);
        }
    }

    function getForgotCooldownStorageKey(email) {
        return `forgot_password_cooldown_until:${String(email || "").trim().toLowerCase()}`;
    }

    function setFieldError(input, errorId, message) {
        const error = document.getElementById(errorId);
        if (input) {
            input.classList.add("is-invalid");
        }
        if (error) {
            error.innerHTML = message || "";
        }
    }

    function clearFieldError(input, errorId) {
        const error = document.getElementById(errorId);
        if (input) {
            input.classList.remove("is-invalid");
        }
        if (error) {
            error.innerHTML = "";
        }
    }

    function checkEmptyField(input, errorId, message) {
        if (!input || !input.value.trim()) {
            setFieldError(input, errorId, message);
            return false;
        }
        clearFieldError(input, errorId);
        return true;
    }

    function validateIdentifier(value) {
        const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
        const phoneRegex = /^(03|05|07|08|09)[0-9]{8}$/;
        const usernameRegex = /^[A-Za-z0-9_-]{3,30}$/;
        return emailRegex.test(value) || phoneRegex.test(value) || usernameRegex.test(value);
    }

    function validateInput() {
        let isValid = true;
        const identifierValue = identifierInput ? identifierInput.value.trim() : "";
        const passwordValue = passwordInput ? passwordInput.value : "";

        if (!checkEmptyField(identifierInput, "identifierError", "Vui lòng nhập email, số điện thoại hoặc tên đăng nhập")) {
            isValid = false;
        } else if (!validateIdentifier(identifierValue)) {
            setFieldError(identifierInput, "identifierError", "Email, số điện thoại hoặc tên đăng nhập không hợp lệ");
            isValid = false;
        }

        if (!checkEmptyField(passwordInput, "passwordError", "Vui lòng nhập mật khẩu")) {
            isValid = false;
        } else if (passwordValue.length < 6) {
            setFieldError(passwordInput, "passwordError", "Mật khẩu tối thiểu 6 ký tự");
            isValid = false;
        }

        return isValid;
    }

    function syncRememberState() {
        if (!rememberMeInput || !identifierInput) {
            return;
        }

        const identifierValue = identifierInput.value.trim();
        const rememberEnabled = rememberMeInput.checked;

        if (rememberEnabled && identifierValue) {
            localStorage.setItem(loginStorageKey, identifierValue);
            localStorage.setItem(loginRememberKey, "1");
        } else {
            localStorage.removeItem(loginStorageKey);
            localStorage.removeItem(loginRememberKey);
        }
    }

    async function checkGoogleAccountNotice() {
        if (!identifierInput) {
            return false;
        }

        const identifierValue = identifierInput.value.trim();
        if (!identifierValue || !validateIdentifier(identifierValue)) {
            return false;
        }

        const requestSeq = ++googleAccountLookupSeq;
        try {
            const lookupUrl = new URL(googleAccountLookupUrl, window.location.origin);
            lookupUrl.searchParams.set("identifier", identifierValue);
            const response = await fetch(lookupUrl.toString(), {
                headers: {
                    "Accept": "application/json",
                    "X-Requested-With": "XMLHttpRequest",
                },
            });
            if (!response.ok) {
                return false;
            }

            const data = await response.json();
            if (requestSeq !== googleAccountLookupSeq) {
                return false;
            }
            if (identifierInput.value.trim() !== identifierValue) {
                return false;
            }

            if (data && data.is_google_account) {
                setFieldError(identifierInput, "identifierError", data.message || googleAccountMessage);
                return true;
            }

            if (document.getElementById("identifierError")?.innerHTML === googleAccountMessage) {
                clearFieldError(identifierInput, "identifierError");
            }
        } catch (_error) {
            return false;
        }

        return false;
    }

    function dangNhapLoad() {
        if (identifierInput && passwordInput && rememberMeInput && !hasServerErrors) {
            const remembered = localStorage.getItem(loginRememberKey) === "1";
            const rememberedIdentifier = localStorage.getItem(loginStorageKey) || "";
            const hasServerValue = identifierInput.value.trim().length > 0;

            if (!hasServerValue && rememberedIdentifier) {
                identifierInput.value = rememberedIdentifier;
            }

            rememberMeInput.checked = remembered && !!identifierInput.value.trim();
            clearFieldError(identifierInput, "identifierError");
            clearFieldError(passwordInput, "passwordError");
        }

        if (passwordInput) {
            passwordInput.value = "";
        }

        const firstInvalidInput = document.querySelector(".is-invalid");
        if (firstInvalidInput) {
            firstInvalidInput.focus();
            return;
        }

        identifierInput?.focus();
    }

    function configureGooglePhoneModal() {
        if (!googlePhonePending) {
            return;
        }

        const displayName = String(googlePhonePendingName || "").trim();
        const email = String(googlePhonePendingEmail || "").trim();
        if (googlePhoneNote) {
            googlePhoneNote.textContent = displayName || email
                ? `Tài khoản ${displayName || email} cần số điện thoại để hoàn tất hồ sơ khách hàng.`
                : "Tài khoản Google của bạn cần số điện thoại để hoàn tất hồ sơ khách hàng.";
        }
        openGooglePhoneModal();
    }

    function togglePasswordField(input, toggleButton, eyeIcon) {
        if (!input || !toggleButton || !eyeIcon) {
            return;
        }

        const isPassword = input.type === "password";
        input.type = isPassword ? "text" : "password";
        toggleButton.setAttribute("aria-pressed", String(isPassword));
        eyeIcon.innerHTML = isPassword
            ? '<path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6S2 12 2 12z"/><path d="M4.5 4.5 19.5 19.5"/>'
            : '<path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>';
    }

    function togglePassword() {
        togglePasswordField(passwordInput, passwordToggle, passwordEye);
    }

    function toggleForgotNewPassword() {
        togglePasswordField(forgotNewPasswordInput, forgotNewPasswordToggle, forgotNewPasswordEye);
    }

    function toggleForgotConfirmPassword() {
        togglePasswordField(forgotConfirmPasswordInput, forgotConfirmPasswordToggle, forgotConfirmPasswordEye);
    }

    async function btnDangNhapClick(event) {
        event.preventDefault();
        const isValid = validateInput();

        if (!isValid) {
            return;
        }

        const isGoogleAccount = await checkGoogleAccountNotice();
        if (isGoogleAccount) {
            return;
        }

        syncRememberState();
        if (loginSubmitBtn) {
            loginSubmitBtn.disabled = true;
            loginSubmitBtn.textContent = "Đang đăng nhập...";
        }
        loginForm?.submit();
    }

    function openGooglePhoneModal() {
        if (!googlePhoneModal) {
            return;
        }
        googlePhoneModal.classList.add("is-open");
        googlePhoneModal.setAttribute("aria-hidden", "false");
        googlePhoneInput?.focus();
    }

    function closeGooglePhoneModal() {
        if (!googlePhoneModal) {
            return;
        }
        googlePhoneModal.classList.remove("is-open");
        googlePhoneModal.setAttribute("aria-hidden", "true");
        if (googlePhoneInput) {
            googlePhoneInput.value = "";
        }
        setFieldError(googlePhoneInput, "googlePhoneMessage", "");
    }

    async function handleGooglePhoneSubmit() {
        if (!googlePhoneInput) {
            return;
        }

        const phone = googlePhoneInput.value.trim();
        const phoneRegex = /^(03|05|07|08|09)[0-9]{8}$/;

        if (!phone) {
            setFieldError(googlePhoneInput, "googlePhoneMessage", "Vui lòng nhập số điện thoại.");
            return;
        }
        if (!phoneRegex.test(phone)) {
            setFieldError(googlePhoneInput, "googlePhoneMessage", "Số điện thoại phải có 10 chữ số và bắt đầu bằng 03, 05, 07, 08 hoặc 09.");
            return;
        }

        try {
            if (googlePhoneSubmit) {
                googlePhoneSubmit.disabled = true;
                googlePhoneSubmit.textContent = "Đang lưu...";
            }
            const data = await postJson(googlePhoneSubmitUrl, { phone });
            if (data.redirect_url) {
                window.location.href = data.redirect_url;
                return;
            }
            window.location.reload();
        } catch (error) {
            setFieldError(googlePhoneInput, "googlePhoneMessage", error.message || "Không thể lưu số điện thoại.");
        } finally {
            if (googlePhoneSubmit) {
                googlePhoneSubmit.disabled = false;
                googlePhoneSubmit.textContent = "Tiếp tục";
            }
        }
    }

    function setForgotMessage(element, message, isSuccess) {
        if (element) {
            element.textContent = message || "";
            element.classList.toggle("forgot-modal__success", Boolean(isSuccess && message));
        }

        if (message && isSuccess && window.AppToast && typeof window.AppToast.success === "function") {
            window.AppToast.success(message);
        }
    }

    function showForgotError(element, message) {
        if (!element) {
            return;
        }

        element.textContent = message || "";
        element.classList.remove("forgot-modal__success");
    }

    function showForgotStep(step) {
        [forgotStepLookup, forgotStepVerify, forgotStepReset].forEach((item) => {
            item?.classList.remove("is-active");
        });

        if (step === "lookup") {
            forgotStepLookup?.classList.add("is-active");
        } else if (step === "verify") {
            forgotStepVerify?.classList.add("is-active");
        } else if (step === "reset") {
            forgotStepReset?.classList.add("is-active");
        }
    }

    function clearResendTimer() {
        if (forgotState.resendTimerId) {
            window.clearInterval(forgotState.resendTimerId);
            forgotState.resendTimerId = null;
        }
        forgotState.resendCooldown = 0;
        if (forgotResendBtn) {
            forgotResendBtn.disabled = false;
            forgotResendBtn.textContent = "Gửi lại OTP";
        }
    }

    function setResendAvailableAt(timestamp) {
        const numericTimestamp = Number(timestamp);
        forgotState.resendAvailableAt = Number.isFinite(numericTimestamp) ? numericTimestamp : null;
    }

    function persistResendAvailableAt(email, timestamp) {
        const key = getForgotCooldownStorageKey(email);
        if (timestamp) {
            sessionStorage.setItem(key, String(timestamp));
        }
    }

    function loadPersistedResendAvailableAt(email) {
        const key = getForgotCooldownStorageKey(email);
        const value = Number(sessionStorage.getItem(key));
        return Number.isFinite(value) && value > 0 ? value : null;
    }

    function clearPersistedResendAvailableAt(email) {
        const key = getForgotCooldownStorageKey(email);
        sessionStorage.removeItem(key);
    }

    function getRemainingResendSeconds() {
        if (!forgotState.resendAvailableAt && forgotState.email) {
            const persisted = loadPersistedResendAvailableAt(forgotState.email);
            if (persisted) {
                setResendAvailableAt(persisted);
            }
        }

        if (!forgotState.resendAvailableAt) {
            return 0;
        }

        const nowSeconds = Math.floor(Date.now() / 1000);
        return Math.max(0, Math.ceil(forgotState.resendAvailableAt - nowSeconds));
    }

    function startResendCooldown(seconds) {
        clearResendTimer();
        forgotState.resendCooldown = Math.max(0, Number(seconds) || 0);
        if (forgotResendBtn) {
            forgotResendBtn.disabled = true;
        }

        const tick = () => {
            if (forgotState.resendCooldown <= 0) {
                clearResendTimer();
                return;
            }

            if (forgotResendBtn) {
                forgotResendBtn.textContent = `Gửi lại OTP (${forgotState.resendCooldown}s)`;
            }
            forgotState.resendCooldown -= 1;
        };

        tick();
        forgotState.resendTimerId = window.setInterval(tick, 1000);
    }

    function resetForgotModal() {
        forgotState.email = "";
        forgotState.resendAvailableAt = null;
        if (forgotEmailInput) forgotEmailInput.value = "";
        if (forgotOtpInput) forgotOtpInput.value = "";
        if (forgotNewPasswordInput) forgotNewPasswordInput.value = "";
        if (forgotConfirmPasswordInput) forgotConfirmPasswordInput.value = "";
        setForgotMessage(forgotLookupMessage, "", false);
        setForgotMessage(forgotVerifyMessage, "", false);
        setForgotMessage(forgotResetMessage, "", false);
        clearResendTimer();
        showForgotStep("lookup");
    }

    function returnToForgotLookup() {
        clearResendTimer();
        resetForgotModal();
        forgotEmailInput?.focus();
    }

    function openForgotModal() {
        resetForgotModal();
        forgotPasswordModal?.classList.add("is-open");
        forgotPasswordModal?.setAttribute("aria-hidden", "false");
        forgotEmailInput?.focus();
    }

    function closeForgotModal() {
        clearResendTimer();
        forgotPasswordModal?.classList.remove("is-open");
        forgotPasswordModal?.setAttribute("aria-hidden", "true");
    }

    async function postJson(url, payload) {
        const response = await fetch(url, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            body: JSON.stringify(payload),
        });

        let data = {};
        try {
            data = await response.json();
        } catch (_error) {
            data = {};
        }

        if (!response.ok) {
            const error = new Error(data.message || "Đã xảy ra lỗi.");
            error.retryAfter = typeof data.retry_after === "number" ? data.retry_after : null;
            throw error;
        }

        return data;
    }

    async function handleForgotLookup() {
        if (!forgotEmailInput) {
            return;
        }

        const email = forgotEmailInput.value.trim();

        if (!email) {
            setForgotMessage(forgotLookupMessage, "Vui lòng nhập email.");
            return;
        }

        const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
        if (!emailRegex.test(email)) {
            setForgotMessage(forgotLookupMessage, "Email không hợp lệ.");
            return;
        }

        try {
            if (forgotLookupBtn) {
                forgotLookupBtn.disabled = true;
                forgotLookupBtn.textContent = "Đang gửi...";
            }
            setForgotMessage(forgotLookupMessage, "Đang gửi mã OTP...", false);
            const data = await postJson(forgotLookupUrl, { email });
            forgotState.email = email;
            if (typeof data.cooldown_until === "number") {
                setResendAvailableAt(data.cooldown_until);
                persistResendAvailableAt(email, data.cooldown_until);
            }
            setForgotMessage(forgotLookupMessage, data.message || "Nếu email hợp lệ, mã OTP đã được gửi.", true);
            showForgotStep("verify");
            forgotOtpInput?.focus();
        } catch (error) {
            showForgotError(forgotLookupMessage, error.message || "Không thể gửi mã OTP lúc này.");
        } finally {
            if (forgotLookupBtn) {
                forgotLookupBtn.disabled = false;
                forgotLookupBtn.textContent = "Gửi mã OTP";
            }
        }
    }

    async function handleForgotVerify() {
        if (!forgotOtpInput) {
            return;
        }

        const otp = forgotOtpInput.value.trim();

        if (!forgotState.email) {
            setForgotMessage(forgotVerifyMessage, "Phiên xác minh đã hết hạn. Vui lòng nhập lại email.");
            showForgotStep("lookup");
            return;
        }

        if (!otp) {
            setForgotMessage(forgotVerifyMessage, "Vui lòng nhập mã OTP.");
            return;
        }

        try {
            const data = await postJson(forgotVerifyUrl, { email: forgotState.email, otp });
            setForgotMessage(forgotVerifyMessage, data.message || "Xác minh OTP thành công.", true);
            showForgotStep("reset");
            forgotNewPasswordInput?.focus();
        } catch (error) {
            showForgotError(forgotVerifyMessage, error.message || "Mã OTP không đúng hoặc đã hết hạn.");
        }
    }

    async function handleForgotResend() {
        if (!forgotState.email) {
            setForgotMessage(forgotVerifyMessage, "Phiên xác minh đã hết hạn. Vui lòng nhập lại email.");
            showForgotStep("lookup");
            return;
        }

        const remainingSeconds = getRemainingResendSeconds();
        if (remainingSeconds > 0) {
            setForgotMessage(forgotVerifyMessage, `Vui lòng chờ ${remainingSeconds} giây trước khi yêu cầu mã mới.`);
            startResendCooldown(remainingSeconds);
            return;
        }

        try {
            const data = await postJson(forgotResendUrl, { email: forgotState.email });
            if (typeof data.cooldown_until === "number") {
                setResendAvailableAt(data.cooldown_until);
                persistResendAvailableAt(forgotState.email, data.cooldown_until);
            }
            setForgotMessage(forgotVerifyMessage, data.message || "Mã OTP đã được gửi lại.", true);
            if (typeof data.retry_after === "number") {
                startResendCooldown(data.retry_after);
            } else if (typeof data.cooldown_until === "number") {
                startResendCooldown(getRemainingResendSeconds());
            }
        } catch (error) {
            if (typeof error.retryAfter === "number") {
                startResendCooldown(error.retryAfter);
            }
            showForgotError(forgotVerifyMessage, error.message || "Không thể gửi lại mã OTP lúc này.");
        }
    }

    async function handleForgotReset() {
        if (!forgotNewPasswordInput || !forgotConfirmPasswordInput) {
            return;
        }

        const newPassword = forgotNewPasswordInput.value;
        const confirmPassword = forgotConfirmPasswordInput.value;

        if (!forgotState.email) {
            setForgotMessage(forgotResetMessage, "Phiên đặt lại đã hết hạn. Vui lòng thực hiện lại từ đầu.");
            showForgotStep("lookup");
            return;
        }

        if (!newPassword || newPassword.length < 6) {
            setForgotMessage(forgotResetMessage, "Mật khẩu mới tối thiểu 6 ký tự.");
            return;
        }

        if (!confirmPassword || confirmPassword.length < 6) {
            setForgotMessage(forgotResetMessage, "Mật khẩu xác nhận tối thiểu 6 ký tự.");
            return;
        }

        if (newPassword !== confirmPassword) {
            setForgotMessage(forgotResetMessage, "Mật khẩu nhập lại không khớp.");
            return;
        }

        try {
            const data = await postJson(forgotResetUrl, {
                email: forgotState.email,
                new_password: newPassword,
                confirm_password: confirmPassword,
            });
            setForgotMessage(forgotResetMessage, data.message || "Mật khẩu đã được cập nhật.", true);
            clearPersistedResendAvailableAt(forgotState.email);
            window.setTimeout(() => {
                closeForgotModal();
                resetForgotModal();
            }, 1200);
        } catch (error) {
            showForgotError(forgotResetMessage, error.message || "Không thể cập nhật mật khẩu.");
        }
    }

    on(identifierInput, "input", function () {
        const value = this.value.trim();
        if (!value) {
            setFieldError(this, "identifierError", "Vui lòng nhập email, số điện thoại hoặc tên đăng nhập");
            return;
        }
        if (!validateIdentifier(value)) {
            setFieldError(this, "identifierError", "Email, số điện thoại hoặc tên đăng nhập không hợp lệ");
            return;
        }
        clearFieldError(this, "identifierError");
    });

    on(identifierInput, "blur", function () {
        const value = this.value.trim();
        if (!value || !validateIdentifier(value)) {
            return;
        }
        void checkGoogleAccountNotice();
    });

    on(passwordInput, "input", function () {
        if (!this.value) {
            setFieldError(this, "passwordError", "Vui lòng nhập mật khẩu");
            return;
        }
        if (this.value.length < 6) {
            setFieldError(this, "passwordError", "Mật khẩu tối thiểu 6 ký tự");
            return;
        }
        clearFieldError(this, "passwordError");
    });

    on(passwordToggle, "click", togglePassword);
    on(forgotNewPasswordToggle, "click", toggleForgotNewPassword);
    on(forgotConfirmPasswordToggle, "click", toggleForgotConfirmPassword);
    on(rememberMeInput, "change", syncRememberState);
    on(loginForm, "submit", btnDangNhapClick);
    on(forgotPasswordBtn, "click", openForgotModal);
    on(forgotPasswordClose, "click", closeForgotModal);
    on(forgotLookupCloseBtn, "click", closeForgotModal);
    on(forgotStepLookup, "submit", function (event) {
        event.preventDefault();
        handleForgotLookup();
    });
    on(forgotBackBtn, "click", returnToForgotLookup);
    on(forgotVerifyBtn, "click", handleForgotVerify);
    on(forgotResendBtn, "click", handleForgotResend);
    on(forgotVerifyCloseBtn, "click", closeForgotModal);
    on(forgotResetBtn, "click", handleForgotReset);
    on(forgotResetCloseBtn, "click", closeForgotModal);
    on(googleLoginBtn, "click", (event) => {
        event.preventDefault();
        window.location.href = googleLoginUrl;
    });
    on(facebookLoginBtn, "click", () => {
        if (window.AppToast && typeof window.AppToast.warning === "function") {
            window.AppToast.warning("Đăng nhập Facebook đang được phát triển.");
        }
    });
    on(googlePhoneClose, "click", closeGooglePhoneModal);
    on(googlePhoneDismiss, "click", closeGooglePhoneModal);
    on(googlePhoneSubmit, "click", handleGooglePhoneSubmit);
    on(googlePhoneInput, "input", function () {
        const value = this.value.trim();
        if (!value) {
            clearFieldError(googlePhoneInput, "googlePhoneMessage");
            return;
        }
        if (!/^(03|05|07|08|09)[0-9]{8}$/.test(value)) {
            setFieldError(googlePhoneInput, "googlePhoneMessage", "Số điện thoại phải có 10 chữ số và bắt đầu bằng 03, 05, 07, 08 hoặc 09.");
            return;
        }
        clearFieldError(googlePhoneInput, "googlePhoneMessage");
    });

    on(forgotPasswordModal, "click", (event) => {
        if (event.target === forgotPasswordModal) {
            closeForgotModal();
        }
    });

    on(document, "keydown", (event) => {
        if (event.key === "Escape" && googlePhoneModal?.classList.contains("is-open")) {
            closeGooglePhoneModal();
            return;
        }
        if (event.key === "Escape" && forgotPasswordModal?.classList.contains("is-open")) {
            closeForgotModal();
        }
    });

    dangNhapLoad();
    configureGooglePhoneModal();
})();
