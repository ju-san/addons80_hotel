# -*- coding: utf-8 -*-
#############################################################################
#
#    OpenERP, Open Source Management Solution
#    Copyright (C) 2012-Today Serpent Consulting Services Pvt. Ltd.
#    (<http://www.serpentcs.com>)
#    Copyright (C) 2004 OpenERP SA (<http://www.openerp.com>)
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>
#
#############################################################################
from openerp.exceptions import except_orm, ValidationError
from openerp.exceptions import Warning as UserError
from openerp.tools import misc, DEFAULT_SERVER_DATETIME_FORMAT
import openerp.addons.decimal_precision as dp
from openerp import models, fields, api, _
from openerp import workflow
from decimal import Decimal
import datetime
import urllib2
import time


def _offset_format_timestamp1(src_tstamp_str, src_format, dst_format,
                              ignore_unparsable_time=True, context=None):
    """
    Convert a source timeStamp string into a destination timeStamp string,
    attempting to apply the
    correct offset if both the server and local timeZone are recognized,or no
    offset at all if they aren't or if tz_offset is false (i.e. assuming they
    are both in the same TZ).

    @param src_tstamp_str: the STR value containing the timeStamp.
    @param src_format: the format to use when parsing the local timeStamp.
    @param dst_format: the format to use when formatting the resulting
     timeStamp.
    @param server_to_client: specify timeZone offset direction (server=src
                             and client=dest if True, or client=src and
                             server=dest if False)
    @param ignore_unparsable_time: if True, return False if src_tstamp_str
                                   cannot be parsed using src_format or
                                   formatted using dst_format.

    @return: destination formatted timestamp, expressed in the destination
             timezone if possible and if tz_offset is true, or src_tstamp_str
             if timezone offset could not be determined.
    """
    if not src_tstamp_str:
        return False
    res = src_tstamp_str
    if src_format and dst_format:
        try:
            # dt_value needs to be a datetime.datetime object\
            # (so notime.struct_time or mx.DateTime.DateTime here!)
            dt_value = datetime.datetime.strptime(src_tstamp_str, src_format)
            if context.get('tz', False):
                try:
                    import pytz
                    src_tz = pytz.timezone(context['tz'])
                    dst_tz = pytz.timezone('UTC')
                    src_dt = src_tz.localize(dt_value, is_dst=True)
                    dt_value = src_dt.astimezone(dst_tz)
                except Exception:
                    pass
            res = dt_value.strftime(dst_format)
        except Exception:
            # Normal ways to end up here are if strptime or strftime failed
            if not ignore_unparsable_time:
                return False
            pass
    return res

class ResPartner(models.Model):
    _inherit = 'res.partner'

    partner_discount = fields.Float(string='Returning Discount')
    partner_type = fields.Selection([('regular', 'Regular'), ('vip', 'VIP'), ('travel', 'Travel Agent')],
                             'Type', default=lambda *a: 'regular')
    
    @api.onchange('partner_discount')
    def _onchange_partner_discount(self):
        if not self.partner_discount:
            return
        if self.partner_discount > 100.0:
            raise except_orm(_('Error'), _('Discount Max is 100%.'))
    
    
class SaleOrder(models.Model):
    _inherit = 'sale.order'
    
    partner_discount = fields.Float(string='Returning Discount')
    partner_type = fields.Selection([('regular', 'Regular'), ('vip', 'VIP'), ('travel', 'Travel Agent')],
                             'Type', default=lambda *a: 'regular')
    
    
    def onchange_partner_id(self, cr, uid, ids, part, context=None):
        val = super(SaleOrder, self).onchange_partner_id(cr, uid, ids, part, context=context)
        part = self.pool.get('res.partner').browse(cr, uid, part, context=context)
        val['value'].update({'partner_discount': part.partner_discount, 'partner_type': part.partner_type})
        #print "===onchange_partner_id===",val
        return val
                
#     @api.multi
#     def _prepare_invoice(self):
#         invoice_vals = super(SaleOrder, self)._prepare_invoice()
#         print "===_prepare_invoice==",invoice_vals
#         invoice_vals['duration'] = self.duration or 1.0
#         invoice_vals['checkin_date'] = self.checkin_date or False
#         invoice_vals['checkout_date'] = self.checkout_date or False
#         invoice_vals['partner_discount'] = self.partner_discount or 0.0
#         invoice_vals['partner_type'] = self.partner_type        
#         return invoice_vals
    
    def _prepare_invoice(self, cr, uid, order, lines, context=None):
        invoice_vals = super(SaleOrder, self)._prepare_invoice(cr, uid, order, lines, context=context)
        #invoice_vals['duration'] = order.duration or 1.0
        #invoice_vals['checkin_date'] = order.checkin_date or False
        #invoice_vals['checkout_date'] = order.checkout_date or False
        invoice_vals['partner_discount'] = order.partner_discount or 0.0
        invoice_vals['partner_type'] = order.partner_type
        return invoice_vals
    
    
class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'
    
    def _calc_line_base_price(self, cr, uid, line, context=None):
        price = line.price_unit
        #if line.type == 'child':
        price = price * (1 - (line.discount or 0.0) / 100.0)
        if line.is_discount:
            price = price * (1 - (line.partner_discount or 0.0) / 100.0)
        return price
    
    def _calc_line_quantity(self, cr, uid, line, context=None):
        return line.product_uom_qty
        #return line.product_uom_qty * line.duration
    
    def _amount_line(self, cr, uid, ids, field_name, arg, context=None):
        tax_obj = self.pool.get('account.tax')
        cur_obj = self.pool.get('res.currency')
        res = {}
        if context is None:
            context = {}
        for line in self.browse(cr, uid, ids, context=context):
            price = self._calc_line_base_price(cr, uid, line, context=context)
            qty = self._calc_line_quantity(cr, uid, line, context=context)
            taxes = tax_obj.compute_all(cr, uid, line.tax_id, price, qty,
                                        line.product_id,
                                        line.order_id.partner_id)
            cur = line.order_id.pricelist_id.currency_id
            res[line.id] = cur_obj.round(cr, uid, cur, taxes['total'])
        return res
    
    @api.model
    def _get_checkin_date(self):
        if self._context.get('tz'):
            to_zone = self._context.get('tz')
        else:
            to_zone = 'UTC'
        return _offset_format_timestamp1(time.strftime("%Y-%m-%d 12:00:00"),
                                         '%Y-%m-%d %H:%M:%S',
                                         '%Y-%m-%d %H:%M:%S',
                                         ignore_unparsable_time=True,
                                         context={'tz': to_zone})

    @api.model
    def _get_checkout_date(self):
        if self._context.get('tz'):
            to_zone = self._context.get('tz')
        else:
            to_zone = 'UTC'
        tm_delta = datetime.timedelta(days=1)
        return datetime.datetime.strptime(_offset_format_timestamp1
                                          (time.strftime("%Y-%m-%d 12:00:00"),
                                           '%Y-%m-%d %H:%M:%S',
                                           '%Y-%m-%d %H:%M:%S',
                                           ignore_unparsable_time=True,
                                           context={'tz': to_zone}),
                                          '%Y-%m-%d %H:%M:%S') + tm_delta
    
    
    @api.onchange('checkout_date', 'checkin_date')
    def onchange_dates(self):
        '''
        This mathod gives the duration between check in and checkout
        if customer will leave only for some hour it would be considers
        as a whole day.If customer will check in checkout for more or equal
        hours, which configured in company as additional hours than it would
        be consider as full days
        --------------------------------------------------------------------
        @param self: object pointer
        @return: Duration and checkout_date
        '''
        company_obj = self.env['res.company']
        configured_addition_hours = 0
        company_ids = company_obj.search([])
#         if company_ids.ids:
#             configured_addition_hours = company_ids[0].additional_hours
        myduration = 0
        chckin = self.checkin_date
        chckout = self.checkout_date
        if chckin and chckout:
            server_dt = DEFAULT_SERVER_DATETIME_FORMAT
            chkin_dt = datetime.datetime.strptime(chckin, server_dt)
            chkout_dt = datetime.datetime.strptime(chckout, server_dt)
            dur = chkout_dt - chkin_dt
            sec_dur = dur.seconds
            if (not dur.days and not sec_dur) or (dur.days and not sec_dur):
                myduration = dur.days
            else:
                myduration = dur.days + 1
#             if configured_addition_hours > 0:
#                 additional_hours = abs((dur.seconds / 60) / 60)
#                 if additional_hours >= configured_addition_hours:
#                     myduration += 1
        self.duration = myduration
                        
    checkin_date = fields.Datetime('Check In', default=_get_checkin_date)
    checkout_date = fields.Datetime('Check Out', default=_get_checkout_date)
    is_discount = fields.Boolean('Is Disc') 
    duration = fields.Float('Duration in Days',
                            help="Number of days which will automatically "
                            "count from the check-in and check-out date. ")
    partner_discount = fields.Float('Disc Cust. (%)', related='order_id.partner_discount', readonly=True, digits= dp.get_precision('Discount'))
    type = fields.Selection([('adult','Adult'),('child','Child')], string='Adult/Child', default='adult')   
    
    def _prepare_order_line_invoice_line(self, cr, uid, line, account_id=False, context=None):
        """Save the layout when converting to an invoice line."""
        invoice_vals = super(SaleOrderLine, self)._prepare_order_line_invoice_line(cr, uid, line, account_id=account_id, context=context)
        if line.type:
            invoice_vals['type'] = line.type
            invoice_vals['duration'] = line.duration or 1.0
            invoice_vals['is_discount'] = line.is_discount or False
            invoice_vals['checkin_date'] = line.checkin_date or False
            invoice_vals['checkout_date'] = line.checkout_date or False
        return invoice_vals
    
class AccountInvoice(models.Model):
    _inherit = 'account.invoice'
    
    partner_discount = fields.Float('Discount Customer (%)', digits= dp.get_precision('Discount'))
    partner_type = fields.Selection([('regular', 'Regular'), ('vip', 'VIP'), ('travel', 'Travel Agent')],
                             'Customer Type', default=lambda *a: 'regular', readonly=True, states={'draft': [('readonly', False)]})
    
    @api.multi
    def confirm_paid(self):
        '''
        This method change pos orders states to done when folio invoice
        is in done.
        ----------------------------------------------------------
        @param self: object pointer
        '''
        pos_order_obj = self.env['pos.order']
        res = super(AccountInvoice, self).confirm_paid()
        pos_ids = pos_order_obj.search([('invoice_id', 'in', self._ids)])
        if pos_ids.ids:
            for pos_id in pos_ids:
                pos_id.write({'state': 'done'})
        return res
    
class AccountInvoiceLine(models.Model):
    _inherit = 'account.invoice.line'
    
    @api.one
    @api.depends('price_unit', 'discount', 'invoice_line_tax_id', 'quantity',
        'product_id', 'invoice_id.partner_id', 'invoice_id.currency_id')
    def _compute_price(self):
        price = self.price_unit
        #if self.type == 'child':
        price = price * (1 - (self.discount or 0.0) / 100.0)
        if self.is_discount:
            price = price * (1 - (self.partner_discount or 0.0) / 100.0)
        taxes = self.invoice_line_tax_id.compute_all(price, self.quantity, product=self.product_id, partner=self.invoice_id.partner_id)
        #taxes = self.invoice_line_tax_id.compute_all(price, self.quantity*self.duration, product=self.product_id, partner=self.invoice_id.partner_id)
        self.price_subtotal = taxes['total']
        if self.invoice_id:
            self.price_subtotal = self.invoice_id.currency_id.round(self.price_subtotal)
    
    checkin_date = fields.Datetime('Check In', readonly=True)
    checkout_date = fields.Datetime('Check Out', readonly=True)    
    is_discount = fields.Boolean('Is Disc') 
    duration = fields.Float('Duration in Days',
                            help="Number of days which will automatically "
                            "count from the check-in and check-out date. ")
    partner_discount = fields.Float('Disc Cust. (%)', related='invoice_id.partner_discount', readonly=True, digits= dp.get_precision('Discount'))
    type = fields.Selection([('adult','Adult'),('child','Child')], string='Adult/Child', default='child')

class AccountInvoiceTax(models.Model):
    _inherit = "account.invoice.tax"
    
    @api.v8
    def compute(self, invoice):
        tax_grouped = {}
        currency = invoice.currency_id.with_context(date=invoice.date_invoice or fields.Date.context_today(invoice))
        company_currency = invoice.company_id.currency_id
        for line in invoice.invoice_line:
            price = line.price_unit
            if line.type == 'child':
                price = price * (1 - (line.discount or 0.0) / 100.0) 
            price = price * (1 - (line.partner_discount or 0.0) / 100.0) 
            taxes = line.invoice_line_tax_id.compute_all(price, line.quantity, line.product_id, invoice.partner_id)['taxes']
            #taxes = line.invoice_line_tax_id.compute_all(price, line.quantity*line.duration, line.product_id, invoice.partner_id)['taxes']
            for tax in taxes:
                val = {
                    'invoice_id': invoice.id,
                    'name': tax['name'],
                    'amount': tax['amount'],
                    'manual': False,
                    'sequence': tax['sequence'],
                    'base': currency.round(tax['price_unit'] * line['quantity']),
                }
                if invoice.type in ('out_invoice','in_invoice'):
                    val['base_code_id'] = tax['base_code_id']
                    val['tax_code_id'] = tax['tax_code_id']
                    val['base_amount'] = currency.compute(val['base'] * tax['base_sign'], company_currency, round=False)
                    val['tax_amount'] = currency.compute(val['amount'] * tax['tax_sign'], company_currency, round=False)
                    val['account_id'] = tax['account_collected_id'] or line.account_id.id
                    val['account_analytic_id'] = tax['account_analytic_collected_id']
                else:
                    val['base_code_id'] = tax['ref_base_code_id']
                    val['tax_code_id'] = tax['ref_tax_code_id']
                    val['base_amount'] = currency.compute(val['base'] * tax['ref_base_sign'], company_currency, round=False)
                    val['tax_amount'] = currency.compute(val['amount'] * tax['ref_tax_sign'], company_currency, round=False)
                    val['account_id'] = tax['account_paid_id'] or line.account_id.id
                    val['account_analytic_id'] = tax['account_analytic_paid_id']

                # If the taxes generate moves on the same financial account as the invoice line
                # and no default analytic account is defined at the tax level, propagate the
                # analytic account from the invoice line to the tax line. This is necessary
                # in situations were (part of) the taxes cannot be reclaimed,
                # to ensure the tax move is allocated to the proper analytic account.
                if not val.get('account_analytic_id') and line.account_analytic_id and val['account_id'] == line.account_id.id:
                    val['account_analytic_id'] = line.account_analytic_id.id

                key = (val['tax_code_id'], val['base_code_id'], val['account_id'])
                if not key in tax_grouped:
                    tax_grouped[key] = val
                else:
                    tax_grouped[key]['base'] += val['base']
                    tax_grouped[key]['amount'] += val['amount']
                    tax_grouped[key]['base_amount'] += val['base_amount']
                    tax_grouped[key]['tax_amount'] += val['tax_amount']

        for t in tax_grouped.values():
            t['base'] = currency.round(t['base'])
            t['amount'] = currency.round(t['amount'])
            t['base_amount'] = currency.round(t['base_amount'])
            t['tax_amount'] = currency.round(t['tax_amount'])

        return tax_grouped