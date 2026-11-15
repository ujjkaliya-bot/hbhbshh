"""Tiny i18n layer for the Telegram UI.

Three reply languages are supported:

* ``en``       — English
* ``hi``       — Hindi in Devanagari script
* ``hinglish`` — Hindi written in Latin script ("mujhe ek bot chahiye")

The bot picks the language per user (see ``ai_coder_agent.detect_language``) and
mirrors whatever the user writes. Code, file names and technical terms always
stay in English.
"""

LANG_EN = "en"
LANG_HI = "hi"
LANG_HINGLISH = "hinglish"
DEFAULT_LANG = LANG_EN

# --------------------------------------------------------------------------- #
# Strings. Keep placeholders in {braces}; they are filled with .format().
# --------------------------------------------------------------------------- #
STRINGS: dict[str, dict[str, str]] = {
    "btn_build_ai": {
        LANG_EN: "✨ Build a New Bot with AI",
        LANG_HI: "✨ AI से नया बॉट बनाएँ",
        LANG_HINGLISH: "✨ AI se naya bot banao",
    },
    "btn_host_zip": {
        LANG_EN: "📦 Host a ZIP Upload",
        LANG_HI: "📦 ZIP अपलोड होस्ट करें",
        LANG_HINGLISH: "📦 ZIP upload host karo",
    },
    "btn_my_bots": {
        LANG_EN: "📂 My Bots & Live Logs",
        LANG_HI: "📂 मेरे बॉट्स और लाइव लॉग",
        LANG_HINGLISH: "📂 Mere bots aur live logs",
    },
    "btn_autofix": {
        LANG_EN: "🩺 AI Auto-Fix (Repair Errors)",
        LANG_HI: "🩺 AI ऑटो-फिक्स (एरर ठीक करें)",
        LANG_HINGLISH: "🩺 AI auto-fix (error theek karo)",
    },
    "btn_help": {
        LANG_EN: "💬 24/7 AI Coding Help",
        LANG_HI: "💬 24/7 AI कोडिंग हेल्प",
        LANG_HINGLISH: "💬 24/7 AI coding help",
    },
    "btn_back": {
        LANG_EN: "⬅️ Back",
        LANG_HI: "⬅️ पीछे",
        LANG_HINGLISH: "⬅️ Back",
    },
    "btn_cancel": {
        LANG_EN: "❌ Cancel",
        LANG_HI: "❌ रद्द करें",
        LANG_HINGLISH: "❌ Cancel",
    },
    "btn_build_now": {
        LANG_EN: "🚀 Build it now",
        LANG_HI: "🚀 अभी बनाएँ",
        LANG_HINGLISH: "🚀 Abhi banao",
    },
    "btn_more_details": {
        LANG_EN: "✏️ Add more details",
        LANG_HI: "✏️ और जानकारी जोड़ें",
        LANG_HINGLISH: "✏️ Aur details do",
    },
    "btn_ai_choose": {
        LANG_EN: "🤖 Let AI Choose (Auto)",
        LANG_HI: "🤖 AI चुने (ऑटो)",
        LANG_HINGLISH: "🤖 AI choose kare (auto)",
    },
    "btn_ai_autofix": {
        LANG_EN: "🩺 AI Auto-Fix",
        LANG_HI: "🩺 AI ऑटो-फिक्स",
        LANG_HINGLISH: "🩺 AI auto-fix",
    },
    "btn_restart": {
        LANG_EN: "🔁 Restart",
        LANG_HI: "🔁 रीस्टार्ट",
        LANG_HINGLISH: "🔁 Restart",
    },
    "btn_packages": {
        LANG_EN: "📦 Packages",
        LANG_HI: "📦 पैकेज",
        LANG_HINGLISH: "📦 Packages",
    },
    "btn_live": {
        LANG_EN: "📡 Live Logs",
        LANG_HI: "📡 लाइव लॉग",
        LANG_HINGLISH: "📡 Live Logs",
    },
    "btn_refresh": {
        LANG_EN: "🔄 Refresh",
        LANG_HI: "🔄 रिफ्रेश",
        LANG_HINGLISH: "🔄 Refresh",
    },
    "btn_live_stop": {
        LANG_EN: "⏹ Stop Live",
        LANG_HI: "⏹ लाइव बंद करें",
        LANG_HINGLISH: "⏹ Live band karo",
    },
    "btn_apply": {
        LANG_EN: "🛠 Auto-Apply & Restart",
        LANG_HI: "🛠 ऑटो-अप्लाई और रीस्टार्ट",
        LANG_HINGLISH: "🛠 Auto-apply aur restart",
    },
    "welcome": {
        LANG_EN: ("👋 <b>Hello {name}!</b>\n\n"
                  "I'm <b>Kilo</b> — your 24/7 <b>AI Coding & Bot Hosting Agent</b>. 🤖\n\n"
                  "I can:\n"
                  "• ✨ Build a brand-new Python/Node.js bot for you with AI\n"
                  "• 📦 Host your existing <code>.zip</code> bot 24/7\n"
                  "• 🩺 Auto-fix crashed bots with AI\n\n"
                  "Pick an option below 👇\n"
                  "<i>Tip: write to me in English, Hindi or Hinglish — I reply in your language.</i>"),
        LANG_HI: ("👋 <b>नमस्ते {name}!</b>\n\n"
                  "मैं <b>Kilo</b> हूँ — आपका 24/7 <b>AI कोडिंग और बॉट होस्टिंग एजेंट</b>. 🤖\n\n"
                  "मैं ये कर सकता हूँ:\n"
                  "• ✨ AI से नया Python/Node.js बॉट बनाऊँ\n"
                  "• 📦 आपका मौजूदा <code>.zip</code> बॉट 24/7 होस्ट करूँ\n"
                  "• 🩺 क्रैश हुए बॉट को AI से ठीक करूँ\n\n"
                  "नीचे से कोई विकल्प चुनें 👇\n"
                  "<i>टिप: मुझे English, हिंदी या Hinglish में लिखें — मैं आपकी भाषा में जवाब दूँगा।</i>"),
        LANG_HINGLISH: ("👋 <b>Namaste {name}!</b>\n\n"
                        "Main <b>Kilo</b> hoon — aapka 24/7 <b>AI coding aur bot hosting agent</b>. 🤖\n\n"
                        "Main ye kar sakta hoon:\n"
                        "• ✨ AI se naya Python/Node.js bot banaun\n"
                        "• 📦 Aapka purana <code>.zip</code> bot 24/7 host karun\n"
                        "• 🩺 Crash hue bot ko AI se theek karun\n\n"
                        "Neeche se koi option chuno 👇\n"
                        "<i>Tip: mujhe English, Hindi ya Hinglish me likho — main aapki language me reply dunga.</i>"),
    },
    "help": {
        LANG_EN: ("<b>📖 Commands</b>\n"
                  "/start – Dashboard\n"
                  "/help – This help\n"
                  "/stop – Turn off AI chat mode\n"
                  "/cancel – Cancel the current flow\n\n"
                  "<b>✨ Build a bot with AI:</b>\n"
                  "1. Tap <b>✨ Build a New Bot with AI</b>\n"
                  "2. Choose a language (or Auto)\n"
                  "3. Describe your idea in your own words (any language)\n"
                  "4. I'll summarise it and ask a few quick questions\n"
                  "5. Tap <b>Build it now</b> — AI writes the code, it's scanned, then deployed 24/7! 🎉\n\n"
                  "<b>📦 Host a ZIP:</b>\n"
                  "1. Tap <b>📦 Host a ZIP Upload</b>\n"
                  "2. Choose a language\n"
                  "3. Send your <code>.zip</code> (Python: <code>main.py</code>/<code>bot.py</code> "
                  "+ <code>requirements.txt</code>; Node: <code>index.js</code> + <code>package.json</code>)"),
        LANG_HI: ("<b>📖 कमांड्स</b>\n"
                  "/start – डैशबोर्ड\n"
                  "/help – यह मदद\n"
                  "/stop – AI चैट मोड बंद करें\n"
                  "/cancel – मौजूदा काम रद्द करें\n\n"
                  "<b>✨ AI से बॉट बनाएँ:</b>\n"
                  "1. <b>✨ AI से नया बॉट बनाएँ</b> दबाएँ\n"
                  "2. भाषा चुनें (या Auto)\n"
                  "3. अपना आइडिया अपने शब्दों में लिखें (कोई भी भाषा)\n"
                  "4. मैं उसे समझकर कुछ छोटे सवाल पूछूँगा\n"
                  "5. <b>अभी बनाएँ</b> दबाएँ — AI कोड लिखेगा, स्कैन होगा, फिर 24/7 डिप्लॉय! 🎉\n\n"
                  "<b>📦 ZIP होस्ट करें:</b>\n"
                  "1. <b>📦 ZIP अपलोड होस्ट करें</b> दबाएँ\n"
                  "2. भाषा चुनें\n"
                  "3. अपनी <code>.zip</code> भेजें (Python: <code>main.py</code>/<code>bot.py</code> "
                  "+ <code>requirements.txt</code>; Node: <code>index.js</code> + <code>package.json</code>)"),
        LANG_HINGLISH: ("<b>📖 Commands</b>\n"
                        "/start – Dashboard\n"
                        "/help – Ye help\n"
                        "/stop – AI chat mode band karo\n"
                        "/cancel – Abhi ka kaam cancel karo\n\n"
                        "<b>✨ AI se bot banao:</b>\n"
                        "1. <b>✨ AI se naya bot banao</b> dabao\n"
                        "2. Language chuno (ya Auto)\n"
                        "3. Apna idea apne shabdon me likho (koi bhi language)\n"
                        "4. Main samajh kar kuch chhote sawaal poochunga\n"
                        "5. <b>Abhi banao</b> dabao — AI code likhega, scan hoga, phir 24/7 deploy! 🎉\n\n"
                        "<b>📦 ZIP host karo:</b>\n"
                        "1. <b>📦 ZIP upload host karo</b> dabao\n"
                        "2. Language chuno\n"
                        "3. Apni <code>.zip</code> bhejo (Python: <code>main.py</code>/<code>bot.py</code> "
                        "+ <code>requirements.txt</code>; Node: <code>index.js</code> + <code>package.json</code>)"),
    },
    "cancelled": {
        LANG_EN: "❌ Cancelled.",
        LANG_HI: "❌ रद्द कर दिया।",
        LANG_HINGLISH: "❌ Cancel kar diya.",
    },
    "ai_off": {
        LANG_EN: "🤖 AI chat mode off. Send /start to open the menu.",
        LANG_HI: "🤖 AI चैट मोड बंद। मेन्यू के लिए /start भेजें।",
        LANG_HINGLISH: "🤖 AI chat mode off. Menu ke liye /start bhejo.",
    },
    "rate_limit": {
        LANG_EN: "⏳ Slow down a little — try again in 10 seconds.",
        LANG_HI: "⏳ थोड़ा धीरे — 10 सेकंड बाद फिर कोशिश करें।",
        LANG_HINGLISH: "⏳ Thoda slow — 10 second baad phir try karo.",
    },
    "rate_limit_short": {
        LANG_EN: "⏳ Rate limit — please wait a moment.",
        LANG_HI: "⏳ रेट लिमिट — थोड़ी देर रुकें।",
        LANG_HINGLISH: "⏳ Rate limit — thodi der ruko.",
    },
    "banned": {
        LANG_EN: "🚫 You have been banned.",
        LANG_HI: "🚫 आप बैन कर दिए गए हैं।",
        LANG_HINGLISH: "🚫 Aap ban kar diye gaye ho.",
    },
    "dashboard": {
        LANG_EN: "🏠 <b>Dashboard</b>\nPick an option 👇",
        LANG_HI: "🏠 <b>डैशबोर्ड</b>\nकोई विकल्प चुनें 👇",
        LANG_HINGLISH: "🏠 <b>Dashboard</b>\nKoi option chuno 👇",
    },
    "choose_lang": {
        LANG_EN: "✨ <b>Build a New Bot with AI</b>\n\nWhich language should I build it in?",
        LANG_HI: "✨ <b>AI से नया बॉट बनाएँ</b>\n\nकिस भाषा में बनाऊँ?",
        LANG_HINGLISH: "✨ <b>AI se naya bot banao</b>\n\nKis language me banaun?",
    },
    "choose_zip_lang": {
        LANG_EN: "📦 <b>Host a ZIP Upload</b>\n\nFirst, choose a language:",
        LANG_HI: "📦 <b>ZIP अपलोड होस्ट करें</b>\n\nपहले भाषा चुनें:",
        LANG_HINGLISH: "📦 <b>ZIP upload host karo</b>\n\nPehle language chuno:",
    },
    "bot_limit": {
        LANG_EN: ("⚠️ You've reached your bot limit ({used}/{limit}).\n"
                  "Ask an admin to run /grant to raise it."),
        LANG_HI: ("⚠️ आपकी बॉट लिमिट पूरी हो गई ({used}/{limit}).\n"
                  "बढ़ाने के लिए एडमिन से /grant चलाने को कहें।"),
        LANG_HINGLISH: ("⚠️ Aapki bot limit poori ho gayi ({used}/{limit}).\n"
                        "Badhane ke liye admin se /grant chalane ko kaho."),
    },
    "ai_not_configured": {
        LANG_EN: ("⚠️ AI is not configured yet. Set the <code>AI_API_KEY</code> "
                  "environment variable and redeploy the service."),
        LANG_HI: ("⚠️ AI अभी कॉन्फ़िगर नहीं है। <code>AI_API_KEY</code> environment "
                  "variable सेट करें और सर्विस रीडिप्लॉय करें।"),
        LANG_HINGLISH: ("⚠️ AI abhi configure nahi hai. <code>AI_API_KEY</code> "
                        "environment variable set karo aur service redeploy karo."),
    },
    "zip_send": {
        LANG_EN: "{pretty} selected ✅\n\nNow send your <b>.zip</b> file (as a document in Telegram).\nSize limit 25 MB.",
        LANG_HI: "{pretty} चुना गया ✅\n\nअब अपनी <b>.zip</b> फ़ाइल भेजें (Telegram में document के रूप में)।\nसाइज़ लिमिट 25 MB।",
        LANG_HINGLISH: "{pretty} chuna gaya ✅\n\nAb apni <b>.zip</b> file bhejo (Telegram me document ke roop me).\nSize limit 25 MB.",
    },
    "describe_idea": {
        LANG_EN: ("{pretty} selected ✅\n\n"
                  "Now describe the bot you want — in your own words (any language is fine).\n\n"
                  "<i>Example: “A Telegram bot that mirrors my channel posts to a group and "
                  "lets admins schedule messages.”</i>\n\n"
                  "I'll restate it, ask a few quick questions, then build it. 🚀"),
        LANG_HI: ("{pretty} चुना गया ✅\n\n"
                  "अब बताएँ आप कैसा बॉट चाहते हैं — अपने शब्दों में (कोई भी भाषा चलेगी)।\n\n"
                  "<i>उदाहरण: “एक Telegram बॉट जो मेरे चैनल की पोस्ट को ग्रुप में भेजे और एडमिन को "
                  "मैसेज शेड्यूल करने दे।”</i>\n\n"
                  "मैं उसे दोबारा समझाऊँगा, कुछ छोटे सवाल पूछूँगा, फिर बना दूँगा। 🚀"),
        LANG_HINGLISH: ("{pretty} chuna gaya ✅\n\n"
                        "Ab batao aap kaisa bot chahte ho — apne shabdon me (koi bhi language chalegi).\n\n"
                        "<i>Example: “Ek Telegram bot jo mere channel ki posts group me bheje aur admins ko "
                        "messages schedule karne de.”</i>\n\n"
                        "Main ise dobara samjhaunga, kuch chhote sawaal poochunga, phir bana dunga. 🚀"),
    },
    "add_details": {
        LANG_EN: "✏️ Sure — send any extra details, and I'll fold them into the plan.",
        LANG_HI: "✏️ ठीक है — कोई भी अतिरिक्त जानकारी भेजें, मैं उसे प्लान में जोड़ दूँगा।",
        LANG_HINGLISH: "✏️ Theek hai — koi bhi extra details bhejo, main plan me jod dunga.",
    },
    "no_bots": {
        LANG_EN: "📂 You don't have any bots yet. Build or host one first!",
        LANG_HI: "📂 अभी आपका कोई बॉट नहीं है। पहले एक बनाएँ या होस्ट करें!",
        LANG_HINGLISH: "📂 Abhi aapka koi bot nahi hai. Pehle ek banao ya host karo!",
    },
    "my_bots": {
        LANG_EN: "<b>📂 My Bots</b>\n",
        LANG_HI: "<b>📂 मेरे बॉट्स</b>\n",
        LANG_HINGLISH: "<b>📂 Mere bots</b>\n",
    },
    "not_yours": {
        LANG_EN: "⛔ This bot isn't yours.",
        LANG_HI: "⛔ यह बॉट आपका नहीं है।",
        LANG_HINGLISH: "⛔ Ye bot aapka nahi hai.",
    },
    "plan_ready": {
        LANG_EN: ("✅ <b>Here's the bot I'll build</b>\n\n{understood}\n\n"
                  "Tap <b>Build it now</b> to generate the code, or add more details."),
        LANG_HI: ("✅ <b>यह बॉट मैं बनाऊँगा</b>\n\n{understood}\n\n"
                  "कोड बनाने के लिए <b>अभी बनाएँ</b> दबाएँ, या और जानकारी जोड़ें।"),
        LANG_HINGLISH: ("✅ <b>Ye bot main banaunga</b>\n\n{understood}\n\n"
                        "Code banane ke liye <b>Abhi banao</b> dabao, ya aur details do."),
    },
    "plan_progress": {
        LANG_EN: ("🧠 <b>Here's what I understand so far</b>\n\n{understood}\n\n"
                  "❓ <b>Question {n}:</b> {question}"),
        LANG_HI: ("🧠 <b>अब तक मैंने यह समझा</b>\n\n{understood}\n\n"
                  "❓ <b>सवाल {n}:</b> {question}"),
        LANG_HINGLISH: ("🧠 <b>Ab tak maine ye samjha</b>\n\n{understood}\n\n"
                        "❓ <b>Sawaal {n}:</b> {question}"),
    },
    "writing_bot_short": {
        LANG_EN: "🧠 Kilo is writing your bot…",
        LANG_HI: "🧠 Kilo आपका बॉट लिख रहा है…",
        LANG_HINGLISH: "🧠 Kilo aapka bot likh raha hai…",
    },
    "writing_bot_eta": {
        LANG_EN: "🧠 Kilo is writing your bot… ({secs}s)\n<i>{base}</i>",
        LANG_HI: "🧠 Kilo आपका बॉट लिख रहा है… ({secs}s)\n<i>{base}</i>",
        LANG_HINGLISH: "🧠 Kilo aapka bot likh raha hai… ({secs}s)\n<i>{base}</i>",
    },
    "building_now": {
        LANG_EN: "🚀 Building now…",
        LANG_HI: "🚀 अभी बना रहा हूँ…",
        LANG_HINGLISH: "🚀 Abhi bana raha hoon…",
    },
    "no_idea_yet": {
        LANG_EN: "⚠️ I don't have your idea yet. Send /start and tap ✨ Build a New Bot with AI.",
        LANG_HI: "⚠️ मेरे पास अभी आपका आइडिया नहीं है। /start भेजें और ✨ AI से नया बॉट बनाएँ दबाएँ।",
        LANG_HINGLISH: "⚠️ Mere paas abhi aapka idea nahi hai. /start bhejo aur ✨ AI se naya bot banao dabao.",
    },
    "no_idea_short": {
        LANG_EN: "⚠️ I don't have your idea yet. Send /start.",
        LANG_HI: "⚠️ मेरे पास अभी आपका आइडिया नहीं है। /start भेजें।",
        LANG_HINGLISH: "⚠️ Mere paas abhi aapka idea nahi hai. /start bhejo.",
    },
    "unsafe_code": {
        LANG_EN: "🛑 The AI's code contained an unsafe pattern, so it was not deployed:\n{reason}",
        LANG_HI: "🛑 AI के कोड में असुरक्षित पैटर्न मिला, इसलिए डिप्लॉय नहीं किया:\n{reason}",
        LANG_HINGLISH: "🛑 AI ke code me unsafe pattern mila, isliye deploy nahi kiya:\n{reason}",
    },
    "files_produced": {
        LANG_EN: ("✨ The AI produced <b>{n}</b> file(s):\n<code>{files}</code>\n\n"
                  "📝 <i>{summary}</i>\n\n🚀 Now deploying to the healthiest server…"),
        LANG_HI: ("✨ AI ने <b>{n}</b> फ़ाइल बनाई:\n<code>{files}</code>\n\n"
                  "📝 <i>{summary}</i>\n\n🚀 अब सबसे बेहतर सर्वर पर डिप्लॉय कर रहा हूँ…"),
        LANG_HINGLISH: ("✨ AI ne <b>{n}</b> file banayi:\n<code>{files}</code>\n\n"
                        "📝 <i>{summary}</i>\n\n🚀 Ab sabse best server par deploy kar raha hoon…"),
    },
    "bot_live": {
        LANG_EN: ("✅ <b>Your AI bot is live!</b> 🎉\n\n"
                  "📝 {summary}\n🆔 <code>{bot_id}</code>\n"
                  "🖥 Server: <b>{server}</b>\n🐍 Language: <b>{language}</b>\n\n"
                  "Open 📂 My Bots to view logs, restart or fix it."),
        LANG_HI: ("✅ <b>आपका AI बॉट लाइव है!</b> 🎉\n\n"
                  "📝 {summary}\n🆔 <code>{bot_id}</code>\n"
                  "🖥 सर्वर: <b>{server}</b>\n🐍 भाषा: <b>{language}</b>\n\n"
                  "लॉग देखने, रीस्टार्ट या ठीक करने के लिए 📂 मेरे बॉट्स खोलें।"),
        LANG_HINGLISH: ("✅ <b>Aapka AI bot live hai!</b> 🎉\n\n"
                        "📝 {summary}\n🆔 <code>{bot_id}</code>\n"
                        "🖥 Server: <b>{server}</b>\n🐍 Language: <b>{language}</b>\n\n"
                        "Logs dekhne, restart ya fix karne ke liye 📂 Mere bots kholo."),
    },
    "deploy_failed": {
        LANG_EN: "❌ Deploy failed: {error}",
        LANG_HI: "❌ डिप्लॉय फेल: {error}",
        LANG_HINGLISH: "❌ Deploy fail: {error}",
    },
    "ai_failed": {
        LANG_EN: "❌ {error}",
        LANG_HI: "❌ {error}",
        LANG_HINGLISH: "❌ {error}",
    },
    "choose_bot_logs": {
        LANG_EN: "📊 Choose a bot to view its logs:",
        LANG_HI: "📊 लॉग देखने के लिए बॉट चुनें:",
        LANG_HINGLISH: "📊 Logs dekhne ke liye bot chuno:",
    },
    "choose_bot_fix": {
        LANG_EN: "🩺 Choose a bot for AI to fix:",
        LANG_HI: "🩺 AI से ठीक कराने के लिए बॉट चुनें:",
        LANG_HINGLISH: "🩺 AI se fix karane ke liye bot chuno:",
    },
    "choose_bot_pkgs": {
        LANG_EN: "📦 Choose a bot to install packages on:",
        LANG_HI: "📦 पैकेज इंस्टॉल करने के लिए बॉट चुनें:",
        LANG_HINGLISH: "📦 Packages install karne ke liye bot chuno:",
    },
    "choose_bot_live": {
        LANG_EN: "📡 Choose a bot to watch live logs:",
        LANG_HI: "📡 लाइव लॉग देखने के लिए बॉट चुनें:",
        LANG_HINGLISH: "📡 Live logs dekhne ke liye bot chuno:",
    },
    "recovered_bots": {
        LANG_EN: "♻️ Recovered {count} bot(s) from the servers after a restart.",
        LANG_HI: "♻️ रीस्टार्ट के बाद सर्वर से {count} बॉट रिकवर हुए।",
        LANG_HINGLISH: "♻️ Restart ke baad server se {count} bot recover hue.",
    },
    "no_bots_found": {
        LANG_EN: "📂 No bots found. Build or host one first!",
        LANG_HI: "📂 कोई बॉट नहीं मिला। पहले एक बनाएँ या होस्ट करें!",
        LANG_HINGLISH: "📂 Koi bot nahi mila. Pehle ek banao ya host karo!",
    },
    "ai_chat_on": {
        LANG_EN: ("💬 <b>24/7 AI Coding Help</b> is active!\n\n"
                  "Ask any coding or hosting question — in English, Hindi or Hinglish. "
                  "Send /stop to end the chat."),
        LANG_HI: ("💬 <b>24/7 AI कोडिंग हेल्प</b> चालू है!\n\n"
                  "कोई भी कोडिंग या होस्टिंग सवाल पूछें — English, हिंदी या Hinglish में। "
                  "चैट खत्म करने के लिए /stop भेजें।"),
        LANG_HINGLISH: ("💬 <b>24/7 AI coding help</b> chalu hai!\n\n"
                        "Koi bhi coding ya hosting sawaal poocho — English, Hindi ya Hinglish me. "
                        "Chat band karne ke liye /stop bhejo."),
    },
    "unknown_action": {
        LANG_EN: "Unknown action.",
        LANG_HI: "अज्ञात क्रिया।",
        LANG_HINGLISH: "Unknown action.",
    },
    "fetching_logs": {
        LANG_EN: "⏳ Fetching logs and RAM usage…",
        LANG_HI: "⏳ लॉग और RAM जानकारी ला रहा हूँ…",
        LANG_HINGLISH: "⏳ Logs aur RAM info la raha hoon…",
    },
    "last_logs": {
        LANG_EN: "Last 40 log lines:",
        LANG_HI: "आखिरी 40 लॉग लाइनें:",
        LANG_HINGLISH: "Aakhri 40 log lines:",
    },
    "live_logs_title": {
        LANG_EN: "📡 <b>Live Logs</b> — {name}",
        LANG_HI: "📡 <b>लाइव लॉग</b> — {name}",
        LANG_HINGLISH: "📡 <b>Live Logs</b> — {name}",
    },
    "live_logs_hint": {
        LANG_EN: ("Updates every 5s for ~2 minutes. "
                  "Tap 🔄 Refresh to keep watching, or ⏹ Stop Live to finish."),
        LANG_HI: ("हर 5 सेकंड में अपडेट, ~2 मिनट तक। "
                  "देखते रहने के लिए 🔄 रिफ्रेश दबाएँ, या ⏹ लाइव बंद करें।"),
        LANG_HINGLISH: ("Har 5s update, ~2 minute tak. "
                        "Dekhte rehne ke liye 🔄 Refresh dabao, ya ⏹ Live band karo."),
    },
    "live_logs_waiting": {
        LANG_EN: "(waiting for output…)",
        LANG_HI: "(आउटपुट का इंतज़ार…)",
        LANG_HINGLISH: "(output ka intezaar…)",
    },
    "live_logs_stopped": {
        LANG_EN: "⏹ Live log stopped. Tap 📊 to fetch logs again.",
        LANG_HI: "⏹ लाइव लॉग बंद। दोबारा देखने के लिए 📊 दबाएँ।",
        LANG_HINGLISH: "⏹ Live log band. Dobara dekhne ke liye 📊 dabao.",
    },
    "pkg_prompt": {
        LANG_EN: ("📦 <b>Install packages</b> for <b>{name}</b>\n\n"
                  "Send the package names, space or comma separated.\n"
                  "Examples:\n"
                  "<code>requests aiohttp</code>\n"
                  "<code>python-telegram-bot&gt;=20 openai</code>\n\n"
                  "They are installed directly (no AI) and the bot is restarted."),
        LANG_HI: ("📦 <b>{name}</b> के लिए पैकेज इंस्टॉल करें\n\n"
                  "पैकेज के नाम भेजें — स्पेस या कॉमा से अलग करके।\n"
                  "उदाहरण:\n"
                  "<code>requests aiohttp</code>\n"
                  "<code>python-telegram-bot&gt;=20 openai</code>\n\n"
                  "ये सीधे इंस्टॉल होंगे (AI के बिना) और बॉट रीस्टार्ट होगा।"),
        LANG_HINGLISH: ("📦 <b>{name}</b> ke liye packages install karo\n\n"
                        "Package names bhejo — space ya comma se alag karke.\n"
                        "Examples:\n"
                        "<code>requests aiohttp</code>\n"
                        "<code>python-telegram-bot&gt;=20 openai</code>\n\n"
                        "Ye seedha install honge (AI ke bina) aur bot restart hoga."),
    },
    "pkg_installing": {
        LANG_EN: "📦 Installing: <code>{pkgs}</code>… this can take up to a minute.",
        LANG_HI: "📦 इंस्टॉल हो रहा है: <code>{pkgs}</code>… एक मिनट तक लग सकता है।",
        LANG_HINGLISH: "📦 Install ho raha hai: <code>{pkgs}</code>… ek minute tak lag sakta hai.",
    },
    "pkg_done": {
        LANG_EN: "✅ <b>Installed:</b> <code>{pkgs}</code>\n\n{restart}",
        LANG_HI: "✅ <b>इंस्टॉल हुआ:</b> <code>{pkgs}</code>\n\n{restart}",
        LANG_HINGLISH: "✅ <b>Install hua:</b> <code>{pkgs}</code>\n\n{restart}",
    },
    "pkg_restarted": {
        LANG_EN: "🔁 Bot restarted so the new packages are loaded.",
        LANG_HI: "🔁 नए पैकेज लोड करने के लिए बॉट रीस्टार्ट हो गया।",
        LANG_HINGLISH: "🔁 Naye packages load karne ke liye bot restart ho gaya.",
    },
    "pkg_failed": {
        LANG_EN: "❌ <b>Install failed.</b>\n\n<pre>{error}</pre>",
        LANG_HI: "❌ <b>इंस्टॉल फेल हुआ।</b>\n\n<pre>{error}</pre>",
        LANG_HINGLISH: "❌ <b>Install fail hua.</b>\n\n<pre>{error}</pre>",
    },
    "pkg_rejected": {
        LANG_EN: "⚠️ Ignored invalid names: <code>{names}</code>",
        LANG_HI: "⚠️ अमान्य नाम छोड़ दिए: <code>{names}</code>",
        LANG_HINGLISH: "⚠️ Invalid naam chhod diye: <code>{names}</code>",
    },
    "pkg_none": {
        LANG_EN: "⚠️ No valid package names found. Try e.g. <code>requests aiohttp</code>.",
        LANG_HI: "⚠️ कोई मान्य पैकेज नाम नहीं मिला। जैसे <code>requests aiohttp</code> भेजें।",
        LANG_HINGLISH: "⚠️ Koi valid package naam nahi mila. Jaise <code>requests aiohttp</code> bhejo.",
    },
    "pkg_output": {
        LANG_EN: "<b>Output:</b>\n<pre>{output}</pre>",
        LANG_HI: "<b>आउटपुट:</b>\n<pre>{output}</pre>",
        LANG_HINGLISH: "<b>Output:</b>\n<pre>{output}</pre>",
    },
    "running": {LANG_EN: "RUNNING", LANG_HI: "चल रहा है", LANG_HINGLISH: "RUNNING"},
    "stopped": {LANG_EN: "STOPPED", LANG_HI: "बंद है", LANG_HINGLISH: "STOPPED"},
    "ai_reading_logs": {
        LANG_EN: "🩺 AI is reading your logs and full code… please wait.",
        LANG_HI: "🩺 AI आपके लॉग और पूरा कोड पढ़ रहा है… कृपया रुकें।",
        LANG_HINGLISH: "🩺 AI aapke logs aur pura code padh raha hai… please wait.",
    },
    "ai_diagnosis": {
        LANG_EN: "🩺 <b>AI Diagnosis</b>",
        LANG_HI: "🩺 <b>AI निदान</b>",
        LANG_HINGLISH: "🩺 <b>AI diagnosis</b>",
    },
    "patched_files": {
        LANG_EN: "Patched files:",
        LANG_HI: "पैच की गई फ़ाइलें:",
        LANG_HINGLISH: "Patched files:",
    },
    "applying_fix": {
        LANG_EN: "🛠 Applying the AI fix…",
        LANG_HI: "🛠 AI का फिक्स लगा रहा हूँ…",
        LANG_HINGLISH: "🛠 AI ka fix laga raha hoon…",
    },
    "fix_applied": {
        LANG_EN: ("✅ Fix applied to <code>{files}</code> and the bot restarted!\n"
                  "(Original files are kept as <code>.bak</code>.)"),
        LANG_HI: ("✅ <code>{files}</code> पर फिक्स लगा और बॉट रीस्टार्ट हो गया!\n"
                  "(पुरानी फ़ाइलें <code>.bak</code> के रूप में रखी हैं।)"),
        LANG_HINGLISH: ("✅ <code>{files}</code> par fix laga aur bot restart ho gaya!\n"
                        "(Purani files <code>.bak</code> ke roop me rakhi hain.)"),
    },
    "apply_failed": {
        LANG_EN: "❌ Auto-apply failed: {error}",
        LANG_HI: "❌ ऑटो-अप्लाई फेल: {error}",
        LANG_HINGLISH: "❌ Auto-apply fail: {error}",
    },
    "please_wait": {
        LANG_EN: "⏳ Please wait…",
        LANG_HI: "⏳ कृपया रुकें…",
        LANG_HINGLISH: "⏳ Please wait…",
    },
    "restarted": {LANG_EN: "🔁 Restarted ✅", LANG_HI: "🔁 रीस्टार्ट हो गया ✅",
                  LANG_HINGLISH: "🔁 Restart ho gaya ✅"},
    "stopped_ok": {LANG_EN: "⏹ Stopped ✅", LANG_HI: "⏹ बंद कर दिया ✅",
                   LANG_HINGLISH: "⏹ Band kar diya ✅"},
    "deleted_ok": {LANG_EN: "🗑 Deleted ✅", LANG_HI: "🗑 हटा दिया ✅",
                   LANG_HINGLISH: "🗑 Delete ho gaya ✅"},
    "send_zip": {
        LANG_EN: "⚠️ Please send a <b>.zip</b> file.",
        LANG_HI: "⚠️ कृपया <b>.zip</b> फ़ाइल भेजें।",
        LANG_HINGLISH: "⚠️ Please <b>.zip</b> file bhejo.",
    },
    "choose_lang_first": {
        LANG_EN: "First choose a language: /start → 📦 Host a ZIP Upload",
        LANG_HI: "पहले भाषा चुनें: /start → 📦 ZIP अपलोड होस्ट करें",
        LANG_HINGLISH: "Pehle language chuno: /start → 📦 ZIP upload host karo",
    },
    "downloading_zip": {
        LANG_EN: "⬇️ Downloading your ZIP…",
        LANG_HI: "⬇️ आपकी ZIP डाउनलोड कर रहा हूँ…",
        LANG_HINGLISH: "⬇️ Aapki ZIP download kar raha hoon…",
    },
    "download_failed": {
        LANG_EN: "❌ Download failed: {error}",
        LANG_HI: "❌ डाउनलोड फेल: {error}",
        LANG_HINGLISH: "❌ Download fail: {error}",
    },
    "zip_rejected": {
        LANG_EN: "🛑 ZIP rejected: {reason}",
        LANG_HI: "🛑 ZIP रिजेक्ट: {reason}",
        LANG_HINGLISH: "🛑 ZIP reject: {reason}",
    },
    "deploying_zip": {
        LANG_EN: ("🚀 Deploying <b>{name}</b> ({language})…\n"
                  "Picking the healthiest server and installing. This can take 1–2 minutes."),
        LANG_HI: ("🚀 <b>{name}</b> ({language}) डिप्लॉय कर रहा हूँ…\n"
                  "सबसे बेहतर सर्वर चुनकर इंस्टॉल कर रहा हूँ। इसमें 1–2 मिनट लग सकते हैं।"),
        LANG_HINGLISH: ("🚀 <b>{name}</b> ({language}) deploy kar raha hoon…\n"
                        "Best server chun kar install kar raha hoon. Isme 1–2 minute lag sakte hain."),
    },
    "zip_live": {
        LANG_EN: ("✅ <b>{name}</b> is live!\n🆔 <code>{bot_id}</code>\n"
                  "🖥 Server: <b>{server}</b>\n📁 <code>{path}</code>\n\n"
                  "The watchdog will keep it running 24/7. 🎉"),
        LANG_HI: ("✅ <b>{name}</b> लाइव है!\n🆔 <code>{bot_id}</code>\n"
                  "🖥 सर्वर: <b>{server}</b>\n📁 <code>{path}</code>\n\n"
                  "वॉचडॉग इसे 24/7 चलाता रहेगा। 🎉"),
        LANG_HINGLISH: ("✅ <b>{name}</b> live hai!\n🆔 <code>{bot_id}</code>\n"
                        "🖥 Server: <b>{server}</b>\n📁 <code>{path}</code>\n\n"
                        "Watchdog ise 24/7 chalta rakhega. 🎉"),
    },
    "lang_python": {LANG_EN: "🐍 Python", LANG_HI: "🐍 Python", LANG_HINGLISH: "🐍 Python"},
    "lang_node": {LANG_EN: "🟩 Node.js", LANG_HI: "🟩 Node.js", LANG_HINGLISH: "🟩 Node.js"},
    "lang_auto": {LANG_EN: "🤖 Auto", LANG_HI: "🤖 ऑटो", LANG_HINGLISH: "🤖 Auto"},
}


def normalize(lang: str | None) -> str:
    """Map anything unknown back to the default language."""
    return lang if lang in (LANG_EN, LANG_HI, LANG_HINGLISH) else DEFAULT_LANG


def t(key: str, lang: str | None = None, **kwargs) -> str:
    """Look up ``key`` in ``lang`` (falling back to English), then format it."""
    entry = STRINGS.get(key)
    if entry is None:
        return key
    template = entry.get(normalize(lang)) or entry.get(DEFAULT_LANG) or key
    if not kwargs:
        return template
    try:
        return template.format(**kwargs)
    except (KeyError, IndexError):
        return template
