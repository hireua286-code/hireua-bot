async def client_form_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    form = context.user_data.get("client_form")

    if not form:
        return False

    text = update.message.text
    step = form.get("step")
    data = form.get("data", {})
    form_type = form.get("type")
    tariff = form.get("tariff", "")

    # ---------- РЕЗЮМЕ ----------
    if form_type == "resume":
        if step == "resume_name":
            data["name"] = text
            form["step"] = "resume_city"
            form["data"] = data
            await update.message.reply_text("📍 Вкажіть місто:")
            return True

        if step == "resume_city":
            data["city"] = text
            form["step"] = "resume_education"
            form["data"] = data
            await update.message.reply_text("🎓 Вкажіть освіту:")
            return True

        if step == "resume_education":
            data["education"] = text
            form["step"] = "resume_specialty"
            form["data"] = data
            await update.message.reply_text("🛠 Вкажіть спеціальність:")
            return True

        if step == "resume_specialty":
            data["specialty"] = text
            form["step"] = "resume_position"
            form["data"] = data
            await update.message.reply_text("💼 Вкажіть бажану посаду:")
            return True

        if step == "resume_position":
            data["position"] = text
            form["step"] = "resume_experience"
            form["data"] = data
            await update.message.reply_text("📋 Опишіть досвід роботи:")
            return True

        if step == "resume_experience":
            data["experience"] = text
            form["step"] = "resume_driver"
            form["data"] = data
            await update.message.reply_text("🚗 Чи є водійське посвідчення?")
            return True

        if step == "resume_driver":
            data["driver"] = text
            form["step"] = "resume_salary"
            form["data"] = data
            await update.message.reply_text("💰 Вкажіть бажану зарплату:")
            return True

        if step == "resume_salary":
            data["salary"] = text
            form["step"] = "resume_contacts"
            form["data"] = data
            await update.message.reply_text("📞 Вкажіть контакти:")
            return True

        if step == "resume_contacts":
            data["contacts"] = text

            admin_text = (
                "📥 Нове резюме\n\n"
                f"Тариф: {tariff}\n"
                f"👤 Ім'я: {data.get('name')}\n"
                f"📍 Місто: {data.get('city')}\n"
                f"🎓 Освіта: {data.get('education')}\n"
                f"🛠 Спеціальність: {data.get('specialty')}\n"
                f"💼 Бажана посада: {data.get('position')}\n"
                f"📋 Досвід роботи: {data.get('experience')}\n"
                f"🚗 Водійське посвідчення: {data.get('driver')}\n"
                f"💰 Бажана зарплата: {data.get('salary')}\n"
                f"📞 Контакти: {data.get('contacts')}"
            )

            await context.bot.send_message(chat_id=ADMIN_ID, text=admin_text)

            await update.message.reply_text(
                "✅ Резюме прийнято.\n"
                "Ми перевіримо інформацію та зв'яжемось з вами."
            )

            context.user_data.pop("client_form", None)
            return True

    # ---------- ВАКАНСІЯ / START / BUSINESS / БАНЕР / REELS ----------
    if step == "company":
        data["company"] = text
        form["step"] = "position"
        form["data"] = data
        await update.message.reply_text("💼 Вкажіть посаду:")
        return True

    if step == "position":
        data["position"] = text
        form["step"] = "city"
        form["data"] = data
        await update.message.reply_text("📍 Вкажіть місто:")
        return True

    if step == "city":
        data["city"] = text
        form["step"] = "address"
        form["data"] = data
        await update.message.reply_text("📍 Вкажіть адресу роботи:")
        return True

    if step == "address":
        data["address"] = text
        form["step"] = "education"
        form["data"] = data
        await update.message.reply_text("🎓 Вкажіть освіту:")
        return True

    if step == "education":
        data["education"] = text
        form["step"] = "experience"
        form["data"] = data
        await update.message.reply_text("📋 Вкажіть досвід роботи:")
        return True

    if step == "experience":
        data["experience"] = text
        form["step"] = "schedule"
        form["data"] = data
        await update.message.reply_text("🕒 Вкажіть графік роботи:")
        return True

    if step == "schedule":
        data["schedule"] = text
        form["step"] = "salary"
        form["data"] = data
        await update.message.reply_text("💰 Вкажіть зарплату:")
        return True

    if step == "salary":
        data["salary"] = text
        form["step"] = "duties"
        form["data"] = data
        await update.message.reply_text("📝 Вкажіть обов'язки:")
        return True

    if step == "duties":
        data["duties"] = text
        form["step"] = "benefits"
        form["data"] = data
        await update.message.reply_text("🎁 Що пропонує компанія?")
        return True

    if step == "benefits":
        data["benefits"] = text
        form["step"] = "contacts"
        form["data"] = data
        await update.message.reply_text("📞 Вкажіть контакти:")
        return True

    if step == "contacts":
        data["contacts"] = text

        if tariff != "БЕЗКОШТОВНО":
            form["step"] = "promo_task"
            form["data"] = data
            await update.message.reply_text(
                "🎯 Що потрібно зробити?\n\n"
                "Наприклад: банер, Reels, Shorts, реклама вакансії, просування компанії."
            )
            return True

        form["step"] = "days"
        form["data"] = data
        await update.message.reply_text("📅 На скільки днів розміщення?\n\n1 / 3 / 7 / 14 / 30")
        return True

    if step == "promo_task":
        data["promo_task"] = text
        form["step"] = "promo_style"
        form["data"] = data
        await update.message.reply_text(
            "🎨 Який стиль потрібен?\n\n"
            "Наприклад: сучасний, яскравий, серйозний, преміум, молодіжний."
        )
        return True

    if step == "promo_style":
        data["promo_style"] = text
        form["step"] = "promo_details"
        form["data"] = data
        await update.message.reply_text(
            "🧩 Що обов'язково треба показати в рекламі?\n\n"
            "Наприклад: логотип, вакансії, зарплата, адреса, команда, переваги."
        )
        return True

    if step == "promo_details":
        data["promo_details"] = text
        form["step"] = "days"
        form["data"] = data
        await update.message.reply_text("📅 На скільки днів розміщення?\n\n1 / 3 / 7 / 14 / 30")
        return True

    if step == "days":
        data["days"] = text

        prompt_block = ""
        if tariff != "БЕЗКОШТОВНО":
            prompt_block = (
                "\n\n🧠 Дані для промпту:\n"
                f"🎯 Завдання: {data.get('promo_task')}\n"
                f"🎨 Стиль: {data.get('promo_style')}\n"
                f"🧩 Обов'язково показати: {data.get('promo_details')}"
            )

        admin_text = (
            "📥 Нова заявка\n\n"
            f"Тариф: {tariff}\n"
            f"🏢 Компанія: {data.get('company')}\n"
            f"💼 Посада: {data.get('position')}\n"
            f"📍 Місто: {data.get('city')}\n"
            f"📍 Адреса: {data.get('address')}\n"
            f"🎓 Освіта: {data.get('education')}\n"
            f"📋 Досвід роботи: {data.get('experience')}\n"
            f"🕒 Графік роботи: {data.get('schedule')}\n"
            f"💰 Зарплата: {data.get('salary')}\n"
            f"📝 Обов'язки: {data.get('duties')}\n"
            f"🎁 Компанія пропонує: {data.get('benefits')}\n"
            f"📞 Контакти: {data.get('contacts')}\n"
            f"📅 Днів розміщення: {data.get('days')}"
            f"{prompt_block}"
        )

        await context.bot.send_message(chat_id=ADMIN_ID, text=admin_text)

        await update.message.reply_text(
            "✅ Заявка прийнята.\n"
            "Ми перевіримо інформацію та зв'яжемось з вами."
        )

        context.user_data.pop("client_form", None)
        return True

    return False