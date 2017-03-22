from openerp import models, fields, api, _
from openerp.exceptions import except_orm, Warning, RedirectWarning
from openerp.tools import float_compare
import openerp.addons.decimal_precision as dp
from openerp.report import report_sxw
from openerp.osv import fields, osv
import locale

import logging
_log = logging.getLogger(__name__)

class AccountVoucher(osv.osv):
    _inherit = "account.voucher"
    
    @api.one
    @api.depends('currency_id', 'payment_rate_currency_id', 'payment_rate', 'amount', 'date', 'journal_id')
    def _compute_rate_amount(self):
        print "--_compute_rate_amount-"
        if self.currency_id != self.payment_rate_currency_id:
            currency_obj = self.env['res.currency']
            currency_str = payment_rate_str = ''
            if self.currency_id:
                currency_str = currency_obj.browse(self.currency_id.id)
            if self.payment_rate_currency_id:
                payment_rate_str = currency_obj.browse(self.payment_rate_currency_id.id)
            #currency_payment = currency_obj.browse(self.currency_id.id)#.rate
            amount_curr = u'%s\N{NO-BREAK SPACE}%s' % (currency_str.symbol, locale.format("%d", payment_rate_str.rate, grouping=True))#formatLang(self.env, currency_payment.rate, currency_obj=self.currency_id)
            amount_curr_payment = u'%s\N{NO-BREAK SPACE}%s' % (payment_rate_str.symbol, locale.format("%d", currency_str.rate, grouping=True))
            #print "====",self.date,currency_str.rate,payment_rate_str.rate
            currency_help_label = _('The exchange rate was %s = %s') % (amount_curr, amount_curr_payment)
            self.amount_info = self.amount * currency_str.rate
            self.currency_inverse_help_label = currency_help_label
    
    def _get_currency_help_label(self, cr, uid, currency_id, payment_rate, payment_rate_currency_id, context=None):
        rml_parser = report_sxw.rml_parse(cr, uid, 'currency_help_label', context=context)
        currency_pool = self.pool.get('res.currency')
        currency_str = payment_rate_str = ''
        if currency_id:
            currency_str = rml_parser.formatLang(1, currency_obj=currency_pool.browse(cr, uid, currency_id, context=context))
        if payment_rate_currency_id:
            payment_rate_str  = rml_parser.formatLang(currency_pool.browse(cr, uid, currency_id, context=context).rate, currency_obj=currency_pool.browse(cr, uid, payment_rate_currency_id, context=context))
        currency_help_label = _('At the operation date, the exchange rate was\n%s = %s') % (currency_str, payment_rate_str)
        return currency_help_label

    def _fnct_currency_help_label(self, cr, uid, ids, name, args, context=None):
        res = {}
        for voucher in self.browse(cr, uid, ids, context=context):
            res[voucher.id] = self._get_currency_help_label(cr, uid, voucher.currency_id.id, voucher.payment_rate, voucher.payment_rate_currency_id.id, context=context)
        return res
    
    def _get_amount_help_label(self, cr, uid, currency_id, payment_rate, payment_rate_currency_id, context=None):
#         rml_parser = report_sxw.rml_parse(cr, uid, 'currency_help_label', context=context)
        currency_pool = self.pool.get('res.currency')
#         currency_str = payment_rate_str = ''
        if currency_id:
            #print "=======",currency_pool.browse(cr, uid, currency_id, context=context).rate
#             currency_str = rml_parser.formatLang(1, currency_obj=currency_pool.browse(cr, uid, currency_id, context=context))
#         if payment_rate_currency_id:
#             payment_rate_str  = rml_parser.formatLang(currency_pool.browse(cr, uid, currency_id, context=context).rate, currency_obj=currency_pool.browse(cr, uid, payment_rate_currency_id, context=context))
#         currency_help_label = _('At the operation date, the exchange rate was\n%s = %s') % (currency_str, payment_rate_str)
            return str(currency_pool.browse(cr, uid, currency_id, context=context).rate)
    
    def _fnct_amount_info_label(self, cr, uid, ids, name, args, context=None):
        res = {}        
        for voucher in self.browse(cr, uid, ids, context=context):
            res[voucher.id] = self._get_amount_help_label(cr, uid, voucher.currency_id.id, voucher.payment_rate, voucher.payment_rate_currency_id.id, context=context)
        return res
    
    _columns = {
        'is_currency': fields.boolean('Is multi currency'),
        'amount_info': fields.function(_fnct_amount_info_label, type='float', string='Amount Rate'),
        'currency_inverse_help_label': fields.text('Rate'),
        'currency_help_label': fields.function(_fnct_currency_help_label, type='text', string="Helping Sentence", help="This sentence helps you to know how to specify the payment rate by giving you the direct effect it has"), 
    }
#     is_currency = fields.Boolean('Is multi currency')
#     amount_info = fields.Float(string='Amount Rate', compute='_compute_rate_amount') 
#     currency_inverse_help_label = fields.Text(string='Helping Rate Sentence', compute='_compute_rate_amount')
    def onchange_rate(self, cr, uid, ids, rate, amount, currency_id, payment_rate_currency_id, company_id, context=None):
        res =  {'value': {'paid_amount_in_company_currency': amount, 'amount_info':  self._get_amount_help_label(cr, uid, currency_id, rate, payment_rate_currency_id, context=context), 'currency_help_label': self._get_currency_help_label(cr, uid, currency_id, rate, payment_rate_currency_id, context=context)}}
        if rate and amount and currency_id:
            company_currency = self.pool.get('res.company').browse(cr, uid, company_id, context=context).currency_id
            #context should contain the date, the payment currency and the payment rate specified on the voucher
            amount_in_company_currency = self.pool.get('res.currency').compute(cr, uid, currency_id, company_currency.id, amount, context=context)
            res['value']['paid_amount_in_company_currency'] = amount_in_company_currency
        return res
        
    def onchange_journal(self, cr, uid, ids, journal_id, line_ids, tax_id, partner_id, date, amount, ttype, company_id, context=None):
        if context is None:
            context = {}
        if not journal_id:
            return False
        journal_pool = self.pool.get('account.journal')
        journal = journal_pool.browse(cr, uid, journal_id, context=context)
        if ttype in ('sale', 'receipt'):
            account_id = journal.default_debit_account_id
        elif ttype in ('purchase', 'payment'):
            account_id = journal.default_credit_account_id
        else:
            account_id = journal.default_credit_account_id or journal.default_debit_account_id
        tax_id = False
        if account_id and account_id.tax_ids:
            tax_id = account_id.tax_ids[0].id
 
        vals = {'value':{} }
        if ttype in ('sale', 'purchase'):
            vals = self.onchange_price(cr, uid, ids, line_ids, tax_id, partner_id, context)
            vals['value'].update({'tax_id':tax_id,'amount': amount})
        currency_id = False
        if journal.currency:
            currency_id = journal.currency.id
        else:
            currency_id = journal.company_id.currency_id.id
 
        period_ids = self.pool['account.period'].find(cr, uid, dt=date, context=dict(context, company_id=company_id))
        is_currency = False
        if journal.currency.id and journal.currency.id != journal.company_id.currency_id.id:
            is_currency = True
        #print "===is_currency====",is_currency,journal.currency.id,journal.company_id.currency_id.id
        vals['value'].update({
            'currency_id': currency_id,
            'payment_rate_currency_id': currency_id,
            'is_currency': is_currency,
            'period_id': period_ids and period_ids[0] or False
        })
        #in case we want to register the payment directly from an invoice, it's confusing to allow to switch the journal 
        #without seeing that the amount is expressed in the journal currency, and not in the invoice currency. So to avoid
        #this common mistake, we simply reset the amount to 0 if the currency is not the invoice currency.
        if context.get('payment_expected_currency') and currency_id != context.get('payment_expected_currency'):
            vals['value']['amount'] = 0
            amount = 0
        if partner_id:
            res = self.onchange_partner_id(cr, uid, ids, partner_id, journal_id, amount, currency_id, ttype, date, context)
            for key in res.keys():
                vals[key].update(res[key])
        return vals
