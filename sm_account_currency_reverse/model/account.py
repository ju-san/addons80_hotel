from openerp import models, fields, api, _
from openerp.exceptions import except_orm, Warning, RedirectWarning
from openerp.tools import float_compare
import openerp.addons.decimal_precision as dp

import logging
_log = logging.getLogger(__name__)

class res_currency(models.Model):
    _inherit = "res.currency"
  
    sm_reverse_rate = fields.Boolean(string='Reverse Rate') 

    def _get_conversion_rate(self, cr, uid, from_currency, to_currency, context=None):
        _log.info ('currrrrrrrrrrrr')
        if context is None:
            context = {}
        ctx = context.copy()
        from_currency = self.browse(cr, uid, from_currency.id, context=ctx)
        to_currency = self.browse(cr, uid, to_currency.id, context=ctx)

        if from_currency.rate == 0 or to_currency.rate == 0:
            date = context.get('date', time.strftime('%Y-%m-%d'))
            if from_currency.rate == 0:
                currency_symbol = from_currency.symbol
            else:
                currency_symbol = to_currency.symbol
            raise osv.except_osv(_('Error'), _('No rate found \n' \
                    'for the currency: %s \n' \
                    'at the date: %s') % (currency_symbol, date))
        if to_currency.base and to_currency.sm_reverse_rate:
            return from_currency.rate/to_currency.rate
        else:
            return to_currency.rate/from_currency.rate
