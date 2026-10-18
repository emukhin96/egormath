(function () {
  'use strict';

  const form = document.querySelector('[data-registration-form]');
  if (!form) return;

  const username = form.querySelector('[data-username-field]');
  const nameFields = Array.from(form.querySelectorAll('[data-name-field]'));
  const password = form.querySelector('[data-password-field]');
  const confirmation = form.querySelector('[data-password-confirmation]');
  const usernamePattern = /^[A-Za-z0-9._-]+$/;
  const namePattern = /^\p{L}+(?:[ '\-’]\p{L}+)*$/u;

  function validateUsername() {
    username.setCustomValidity('');
    if (!username.value) return true;
    if (username.value.length < 3 || username.value.length > username.maxLength) {
      username.setCustomValidity('Логин должен содержать от 3 до 30 символов.');
    } else if (!usernamePattern.test(username.value)) {
      username.setCustomValidity(
        'Используйте только латинские буквы, цифры, точку, дефис и подчёркивание.'
      );
    }
    return username.validity.valid;
  }

  function validateName(field) {
    field.setCustomValidity('');
    if (!field.value) return true;
    if (field.value.length > field.maxLength) {
      field.setCustomValidity('Введите не больше 50 символов.');
    } else if (!namePattern.test(field.value)) {
      field.setCustomValidity('Используйте только буквы, пробел, дефис или апостроф.');
    }
    return field.validity.valid;
  }

  function validatePassword() {
    password.setCustomValidity('');
    if (!password.value) return true;
    if (password.value.length < 6 || password.value.length > password.maxLength) {
      password.setCustomValidity('Пароль должен содержать от 6 до 128 символов.');
    }
    return password.validity.valid;
  }

  function validateConfirmation() {
    confirmation.setCustomValidity('');
    if (confirmation.value && confirmation.value !== password.value) {
      confirmation.setCustomValidity('Пароли не совпадают.');
    }
    return confirmation.validity.valid;
  }

  username.addEventListener('blur', function () {
    username.value = username.value.trim().toLowerCase();
    validateUsername();
  });
  username.addEventListener('input', validateUsername);

  nameFields.forEach(function (field) {
    field.addEventListener('blur', function () {
      field.value = field.value.trim().replace(/\s+/g, ' ');
      validateName(field);
    });
    field.addEventListener('input', function () { validateName(field); });
  });

  password.addEventListener('blur', validatePassword);
  password.addEventListener('input', function () {
    validatePassword();
    if (confirmation.value) validateConfirmation();
  });
  confirmation.addEventListener('blur', validateConfirmation);
  confirmation.addEventListener('input', validateConfirmation);

  // Подсказка логина транслитом из фамилии и имени — как generate_username
  // на сервере; работает, пока логин не введён вручную.
  if (form.hasAttribute('data-suggest-username')) {
    const TRANSLIT = {
      'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'e',
      'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'j', 'к': 'k', 'л': 'l', 'м': 'm',
      'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
      'ф': 'f', 'х': 'h', 'ц': 'c', 'ч': 'ch', 'ш': 'sh', 'щ': 'sch',
      'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya',
    };
    const firstName = form.querySelector('[name="first_name"]');
    const lastName = form.querySelector('[name="last_name"]');
    let typedByUser = username.value !== '';
    username.addEventListener('input', function () { typedByUser = username.value !== ''; });
    const suggestUsername = function () {
      if (typedByUser) return;
      const raw = (lastName.value.trim() + '.' + firstName.value.trim()).toLowerCase();
      const latin = Array.from(raw).map(function (ch) {
        return Object.prototype.hasOwnProperty.call(TRANSLIT, ch) ? TRANSLIT[ch] : ch;
      }).join('');
      username.value = latin.replace(/[^a-z0-9\s_-]/g, '').replace(/[-\s]+/g, '-')
        .replace(/^[-_]+|[-_]+$/g, '').slice(0, 24);
      validateUsername();
    };
    nameFields.forEach(function (field) { field.addEventListener('blur', suggestUsername); });
  }

  form.addEventListener('submit', function (event) {
    const valid = [
      validateUsername(),
      nameFields.every(validateName),
      validatePassword(),
      validateConfirmation(),
    ].every(Boolean);
    if (!valid || !form.checkValidity()) {
      event.preventDefault();
      form.reportValidity();
    }
  });
})();
