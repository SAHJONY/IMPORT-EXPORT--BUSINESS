/* SAHJONY LLC — public company identity (single source of truth).
 * Used by the Trust Center and any public page that must display the
 * legal identity of the business. Edit values here only.
 *
 * Standing owner rule: street address and company registration are
 * intentionally omitted from the public site. streetAddress and
 * registrationNumber stay empty; renderers must print NOTHING for them
 * (no placeholders, no "pending" labels, no explanatory notices).
 * Do NOT invent values here.
 */
window.SAHJONY_COMPANY = {
  legalName: 'SAHJONY LLC',
  streetAddress: '', // intentionally empty per owner rule — render nothing
  city: 'Houston',
  state: 'Texas',
  postalCode: '', // intentionally empty per owner rule — render nothing
  country: 'USA',
  registrationNumber: '', // intentionally empty per owner rule — render nothing
  registrationAuthority: '', // intentionally empty per owner rule — render nothing
  phoneVoice: '+1 281-662-8581',
  phoneWhatsApp: '+1 281-662-8581',
  emailSales: 'ventas@sahjony.com',
  emailCuba: 'cuba@sahjony.com',
  website: 'https://www.sahjony.com'
};
