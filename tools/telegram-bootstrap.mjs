import process from 'node:process';

const token = String(process.env.TELEGRAM_BOT_TOKEN || '').trim();
const channelId = String(process.env.TELEGRAM_CHANNEL_ID || '').trim();
const botUsername = String(process.env.TELEGRAM_BOT_USERNAME || 'Sahjonywholesale_bot').replace(/^@/, '');
const publicUrl = `https://t.me/${botUsername}`;
const businessPhoneDisplay = String(process.env.SAHJONY_BUSINESS_PHONE_DISPLAY || '+1 281-662-8581').trim();
const businessPhoneE164 = String(process.env.SAHJONY_BUSINESS_PHONE_E164 || '+12816628581').trim();
const whatsappUrl = `https://wa.me/${businessPhoneE164.replace(/\D/g, '')}`;

if (!token) throw new Error('TELEGRAM_BOT_TOKEN is required');

async function call(method, payload = {}) {
  const response = await fetch(`https://api.telegram.org/bot${token}/${method}`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok || !data.ok) throw new Error(`${method}: ${data.description || response.status}`);
  return data.result;
}

const commands = [
  { command: 'start', description: 'Abrir SAHJONY y hablar con Sofía' },
  { command: 'cotizar', description: 'Solicitar una cotización' },
  { command: 'comprar', description: 'Necesito comprar o importar' },
  { command: 'vender', description: 'Quiero ofrecer productos o capacidad' },
  { command: 'carga', description: 'Carga consolidada y envíos' },
  { command: 'vehiculo', description: 'Envío marítimo de vehículos a Cuba' },
  { command: 'mipyme', description: 'Compras/importación/exportación para MIPYMES' },
  { command: 'proveedor', description: 'Registro y evaluación de proveedores' },
  { command: 'whatsapp', description: `WhatsApp oficial ${businessPhoneDisplay}` },
  { command: 'estado', description: 'Estado de una operación existente' },
  { command: 'ayuda', description: 'Opciones y contacto' },
];

await call('setMyCommands', { commands, language_code: 'es' });
await call('setMyShortDescription', {
  short_description: `Sofía de SAHJONY: compras, carga, vehículos y MIPYMES. WhatsApp ${businessPhoneDisplay}.`,
  language_code: 'es',
});
await call('setMyDescription', {
  description: `Canal comercial oficial de SAHJONY GLOBAL TRADING. Sofía atiende 24/7 compras, importación/exportación, carga consolidada, vehículos, proveedores y MIPYMES. WhatsApp oficial: ${businessPhoneDisplay}. Telegram opera en paralelo y no sustituye ni desconecta la cuenta de WhatsApp. Las cotizaciones formales dependen de verificación de costos, ruta, compliance y disponibilidad.`,
  language_code: 'es',
});
await call('setChatMenuButton', {
  menu_button: { type: 'web_app', text: 'SAHJONY', web_app: { url: 'https://www.sahjony.com/' } },
}).catch(async () => {
  await call('setChatMenuButton', { menu_button: { type: 'commands' } });
});

let launchMessageId = null;
if (channelId) {
  const launchText = [
    '🚀 SAHJONY GLOBAL TRADING — CANAL OFICIAL',
    '',
    'Sofía Smith atiende este canal 24/7 para:',
    '• Carga consolidada y envíos a Cuba',
    '• Envío marítimo de vehículos',
    '• Compras y sourcing internacional',
    '• MIPYMES y emprendedores privados cubanos',
    '• Proveedores mayoristas y oportunidades comerciales',
    '• Importación, exportación y logística',
    '',
    `📱 WhatsApp oficial SAHJONY: ${businessPhoneDisplay}`,
    'Telegram y WhatsApp funcionan como canales paralelos. Este enlace no modifica ni desconecta la cuenta de WhatsApp.',
    '',
    '📩 Inicia una conversación con Sofía para solicitar cotización o presentar una necesidad comercial.',
    '',
    'Las tarifas, rutas, disponibilidad y condiciones comerciales se confirman antes de cualquier cotización formal.',
    '',
    publicUrl,
    'www.sahjony.com',
  ].join('\n');

  const message = await call('sendMessage', {
    chat_id: channelId,
    text: launchText,
    disable_web_page_preview: false,
    reply_markup: {
      inline_keyboard: [
        [{ text: '💬 Hablar con Sofía', url: `${publicUrl}?start=trade` }],
        [{ text: '📱 WhatsApp oficial', url: whatsappUrl }],
        [{ text: '🌐 SAHJONY', url: 'https://www.sahjony.com/' }],
      ],
    },
  });
  launchMessageId = message.message_id;
  await call('pinChatMessage', {
    chat_id: channelId,
    message_id: launchMessageId,
    disable_notification: true,
  }).catch(() => null);
}

const me = await call('getMe');
console.log(JSON.stringify({
  ok: true,
  bot: me.username,
  publicUrl,
  whatsapp: {
    phone: businessPhoneDisplay,
    url: whatsappUrl,
    connectionTouched: false,
  },
  channelConfigured: Boolean(channelId),
  launchMessageId,
  commandsConfigured: commands.length,
}, null, 2));
