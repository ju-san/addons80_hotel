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

from openerp.tools import DEFAULT_SERVER_DATETIME_FORMAT
from openerp.exceptions import except_orm, ValidationError
from dateutil.relativedelta import relativedelta
from openerp import models, fields, api, _
import openerp.addons.decimal_precision as dp
import datetime
import time


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
    
    
class HotelFolio(models.Model):
    _inherit = 'hotel.folio'
    _order = 'reservation_id desc'

    reservation_id = fields.Many2one(comodel_name='hotel.reservation', string='Reservation')


class HotelFolioLineExt(models.Model):
    _inherit = 'hotel.folio.line'

    @api.multi
    def write(self, vals):
        """
        Overrides orm write method.
        @param self: The object pointer
        @param vals: dictionary of fields value.
        """
        """update Hotel Room Reservation line history"""
        reservation_line_obj = self.env['hotel.room.reservation.line']
        room_obj = self.env['hotel.room']
        prod_id = vals.get('product_id') or self.product_id.id
        chkin = vals.get('checkin_date') or self.checkin_date
        chkout = vals.get('checkout_date') or self.checkout_date
        is_reserved = self.is_reserved

        if prod_id and is_reserved:
            prod_domain = [('product_id', '=', prod_id)]
            prod_room = room_obj.search(prod_domain, limit=1)

            if (self.product_id and self.checkin_date and self.checkout_date):
                old_prd_domain = [('product_id', '=', self.product_id.id)]
                old_prod_room = room_obj.search(old_prd_domain, limit=1)
                if prod_room and old_prod_room:
                    # check for existing room lines.
                    srch_rmline = [('room_id', '=', old_prod_room.id),
                                   ('check_in', '=', self.checkin_date),
                                   ('check_out', '=', self.checkout_date),
                                   ]
                    rm_lines = reservation_line_obj.search(srch_rmline)
                    if rm_lines:
                        rm_line_vals = {'room_id': prod_room.id,
                                        'check_in': chkin,
                                        'check_out': chkout}
                        rm_lines.write(rm_line_vals)
        return super(HotelFolioLineExt, self).write(vals)


class HotelReservation(models.Model):
    _name = "hotel.reservation"
    _rec_name = "reservation_no"
    _description = "Reservation"
    _order = 'reservation_no desc'
    _inherit = ['mail.thread', 'ir.needaction_mixin']
    
#     date_a = (datetime.datetime(*time.strptime(reservation['checkout'],DEFAULT_SERVER_DATETIME_FORMAT)[:5]))
#     date_b = (datetime.datetime(*time.strptime(reservation['checkin'],DEFAULT_SERVER_DATETIME_FORMAT)[:5]))
    
    @api.one
    @api.depends('checkin', 'checkout')
    def _compute_duration(self):
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
        if company_ids.ids:
            configured_addition_hours = company_ids[0].additional_hours
        myduration = 0
        chckin = self.checkin#_date
        chckout = self.checkout#_date
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
            if configured_addition_hours > 0:
                additional_hours = abs((dur.seconds / 60) / 60)
                if additional_hours >= configured_addition_hours:
                    myduration += 1
        self.duration = myduration
        
    @api.one
    @api.depends('reservation_package_line.price_subtotal', 'reservation_room_line.price_subtotal', 'reservation_service_line.price_subtotal')
    def _amount_all(self):
        """
        Compute the total amounts of the SO.
        """
        voucher_obj = self.env['account.voucher'] 
        for order in self:
            amount_untaxed = amount_deposit = amount_tax = 0.0
            for pline in order.reservation_package_line:
                amount_untaxed += pline.price_subtotal
                amount_tax += pline.price_tax
            for rline in order.reservation_room_line:
                amount_untaxed += rline.price_subtotal
                amount_tax += rline.price_tax
            for sline in order.reservation_service_line:
                amount_untaxed += sline.price_subtotal
                amount_tax += sline.price_tax
            for deposit in voucher_obj.search([('partner_id','=',order.partner_id.id)]):
                if deposit.state == 'draft':
                    amount_deposit += deposit.amount
            order.update({
                'amount_deposit': amount_deposit,
                'amount_untaxed': order.pricelist_id.currency_id.round(amount_untaxed),
                'amount_tax': order.pricelist_id.currency_id.round(amount_tax),
                'amount_total': amount_untaxed + amount_tax,
            })
    
    reservation_no = fields.Char('Reservation No', size=64, readonly=True)
    date_order = fields.Datetime('Date Ordered', required=True, readonly=True,
                                 states={'draft': [('readonly', False)]},
                                 default=(lambda *a: time.strftime(DEFAULT_SERVER_DATETIME_FORMAT)))
    date_expire = fields.Datetime('Auto Cancel Reservation', required=True, readonly=True, states={'draft': [('readonly', False)]})
    partner_discount = fields.Float(string='Discount Customer', readonly=True, states={'draft': [('readonly', False)]})
    partner_type = fields.Selection([('regular', 'Regular'), ('vip', 'VIP'), ('travel', 'Travel Agent')],
                             'Customer Type', default=lambda *a: 'regular', readonly=True, states={'draft': [('readonly', False)]})
    reserve_type = fields.Selection([('room', 'Room'), ('service', 'Service'), ('package', 'Package')],
                             'Reservation Type', default=lambda *a: 'room', required=True, readonly=True, states={'draft': [('readonly', False)]})
    warehouse_id = fields.Many2one('stock.warehouse', 'Hotel', readonly=True,
                                   required=True, default=1,
                                   states={'draft': [('readonly', False)]})
    partner_id = fields.Many2one('res.partner', 'Guest Name', readonly=True,
                                 required=True,
                                 states={'draft': [('readonly', False)]})
    pricelist_id = fields.Many2one('product.pricelist', 'Scheme',
                                   required=True, readonly=True,
                                   states={'draft': [('readonly', False)]},
                                   help="Pricelist for current reservation.")
    partner_invoice_id = fields.Many2one('res.partner', 'Invoice Address',
                                         readonly=True, states={'draft': [('readonly', False)]},
                                         help="Invoice address for "
                                         "current reservation.")
    partner_order_id = fields.Many2one('res.partner', 'Ordering Contact',
                                       readonly=True,
                                       states={'draft':
                                               [('readonly', False)]},
                                       help="The name and address of the "
                                       "contact that requested the order "
                                       "or quotation.")
    partner_shipping_id = fields.Many2one('res.partner', 'Delivery Address',
                                          readonly=True,
                                          states={'draft':
                                                  [('readonly', False)]},
                                          help="Delivery address"
                                          "for current reservation. ")
    checkin = fields.Datetime('Expected-Date-Arrival', required=True, readonly=True, states={'draft': [('readonly', False)]})
    checkout = fields.Datetime('Expected-Date-Departure', required=True, readonly=True, states={'draft': [('readonly', False)]})
    duration = fields.Float('Duration in Days', digits=dp.get_precision('Product UoS'), compute='_compute_duration',
                            help="Number of days which will automatically "
                            "count from the check-in and check-out date. ")
    adults = fields.Integer('Adults', size=64, readonly=True,
                            states={'draft': [('readonly', False)]},
                            help='List of adults there in guest list. ')
    children = fields.Integer('Children', size=64, readonly=True,
                              states={'draft': [('readonly', False)]},
                              help='Number of children there in guest list.')
    room_to_reserve = fields.Many2many('hotel.room',
                               'hotel_room_to_reserve_rel',
                               'hotel_reservation_id', 'room_id',
                               domain="[('isroom','=',True)]", string="Room to Reserve", readonly=True, states={'draft': [('readonly', False)]})
    service_to_reserve = fields.Many2many('hotel.services',
                               'hotel_services_to_reserve_rel',
                               'hotel_reservation_id', 'service_id',
                               domain="[('isservice','=',True)]", string="Service to Reserve", readonly=True, states={'draft': [('readonly', False)]})
    #reservation_line2 = fields.One2many('hotel_reservation.line2', 'line_id', 'Service Reserve', help='Hotel service reservation details.')
    reservation_line = fields.One2many('hotel_reservation.line', 'line_id', 'Room Reserve', help='Hotel room reservation details.')
    reservation_package_line = fields.One2many('hotel_reservation.package.line', 'line_id', 'Package Reservation',readonly=True, states={'draft': [('readonly', False)]}, help='Hotel package reservation details.')
    reservation_room_line = fields.One2many('hotel_reservation.room.line', 'line_id', 'Rooms',readonly=True, states={'draft': [('readonly', False)]}, help='Hotel room reservation details.')
    reservation_service_line = fields.One2many('hotel_reservation.service.line', 'line_id', 'Services',readonly=True, states={'draft': [('readonly', False)]}, help='Hotel service reservation details.')
    state = fields.Selection([('draft', 'Draft'), ('confirm', 'Confirm'),
                              ('cancel', 'Cancel'), ('done', 'Done')],
                             'State', readonly=True,
                             default=lambda *a: 'draft')
    folio_id = fields.Many2many('hotel.folio', 'hotel_folio_reservation_rel',
                                'order_id', 'invoice_id', string='Folio')
    company_id = fields.Many2one('res.company', string='Company', required=True,
                                 default=lambda self: self.env.user.company_id, readonly=True, states={'draft': [('readonly', False)]})
    dummy = fields.Datetime('Dummy')    
    hide_me = fields.Boolean('Hide')
    tax_id = fields.Many2many('account.tax', string='Taxes', domain=['|', ('active', '=', False), ('active', '=', True)])
    #amount_discount = fields.Float(string='Discount', store=True, readonly=True, compute='_amount_all', track_visibility='always')
    amount_deposit = fields.Float(string='Deposit', store=True, readonly=True, compute='_amount_all', track_visibility='always')
    amount_untaxed = fields.Float(string='Untaxed Amount', store=True, readonly=True, compute='_amount_all', track_visibility='always')
    amount_tax = fields.Float(string='Taxes', store=True, readonly=True, compute='_amount_all', track_visibility='always')
    amount_total = fields.Float(string='Total', store=True, readonly=True, compute='_amount_all', track_visibility='always')
    
    note = fields.Text()
    
#     @api.model
#     def _amount_line_tax(self, line):
#         taxes = line.tax_id.filtered(lambda t: t.company_id.id == line.line_id.company_id.id)
#         price = line.price_unit * (1 - (line.discount or 0.0) / 100.0)
#         taxes = taxes.compute_all(price, line.line_id.pricelist_id.currency_id, line.quantity, product=line.package_id.package_id, partner=line.line_id.partner_id or False)['taxes']
#         return sum(tax.get('amount', 0.0) for tax in taxes)
    
    @api.onchange('partner_discount')
    def _onchange_partner_discount(self):
        if not self.partner_discount:
            return
        self.partner_discount = self.partner_id.partner_discount
    
    @api.onchange('reservation_package_line')
    def _onchange_reservation_package_line(self):
        if not self.reservation_package_line:
            return
        room_lines = []
        service_lines = []
        if self.reservation_package_line.reserve_room:
            room_lines = [self.reservation_package_line.reserve_room.id]
        if self.reservation_package_line.reserve_ser:
            service_lines = [self.reservation_package_line.reserve_ser.id]
        self.room_to_reserve = room_lines
        self.service_to_reserve = service_lines
        return
    
    @api.onchange('reservation_room_line')
    def _onchange_reservation_room_line(self):
        if not self.reservation_room_line:
            return
        room_lines = []
        for room in self.reservation_room_line:
            room_lines.append(room.room_id.id)
        self.room_to_reserve = room_lines
        return

    @api.onchange('reservation_service_line')
    def _onchange_reservation_service_line(self):
        if not self.reservation_service_line:
            return
        service_lines = []
        for service in self.reservation_service_line:
            service_lines.append(service.service_id.id)
        self.service_to_reserve = service_lines
        return

    @api.multi
    def button_dummy(self):
        room_lines = []
        service_lines = []        
        #CUT LINK
        for room in self.room_to_reserve:
            self.write({'room_to_reserve': [(3, room.id)]})
        for serv in self.service_to_reserve:
            self.write({'service_to_reserve': [(3, serv.id)]})
        #PACKAGE
        if self.reservation_package_line.reserve_room:
            room_lines = [self.reservation_package_line.reserve_room.id]
        if self.reservation_package_line.reserve_ser:
            service_lines = [self.reservation_package_line.reserve_ser.id]
        #ROOM
        for rroom in self.reservation_room_line:
            room_lines.append(rroom.room_id.id)
        #SERVICE
        for svrs in self.reservation_service_line:
            service_lines.append(svrs.service_id.id)
        self._onchange_reservation_package_line()
        self._onchange_reservation_room_line()
        self._onchange_reservation_service_line()
        return True
    
    @api.multi
    def unlink(self):
        """
        Overrides orm unlink method.
        @param self: The object pointer
        @return: True/False.
        """
        for reserv_rec in self:
            if reserv_rec.state != 'draft':
                raise ValidationError(_('You can not delete Reservation in %s\
                state.') % (reserv_rec.state))
        return super(HotelReservation, self).unlink()

    @api.constrains('reservation_line', 'adults', 'children')
    def check_reservation_rooms(self):
        '''
        This method is used to validate the reservation_line.
        -----------------------------------------------------
        @param self: object pointer
        @return: raise a warning depending on the validation
        '''
        for reservation in self:
            if not reservation.room_to_reserve:
                raise ValidationError(_('Please Select Rooms For Reservation.'))
#             for rec in reservation.room_to_reserve:
#                 if len(rec.reserve) == 0:
#                     raise ValidationError(_('Please Select Rooms For Reservation.'))
#                 cap = 0
#                 for room in rec.reserve:
#                     cap += room.capacity
                #if (self.adults + self.children) > cap:
                #        raise ValidationError(_('Room Capacity Exceeded \nPlease Select Rooms According to Members Accomodation.'))

    @api.constrains('checkin', 'checkout')
    def check_in_out_dates(self):
        """
        When date_order is less then checkin date or
        Checkout date should be greater than the checkin date.
        """
        if self.checkout and self.checkin:
            #print "=====",self.checkin<self.date_order
            if self.checkin < self.date_order:
                raise except_orm(_('Warning'), _('Checkin date should be \
                greater than the current date.'))
            if self.checkout < self.checkin:
                raise except_orm(_('Warning'), _('Checkout date \
                should be greater than Checkin date.'))

    @api.model
    def _needaction_count(self, domain=None):
        """
         Show a count of draft state reservations on the menu badge.
         """
        return self.search_count([('state', '=', 'draft')])

    @api.onchange('checkout', 'checkin')
    def on_change_checkout(self):
        '''
        When you change checkout or checkin update dummy field
        -----------------------------------------------------------
        @param self: object pointer
        @return: raise warning depending on the validation
        '''
        checkout_date = time.strftime(DEFAULT_SERVER_DATETIME_FORMAT)
        checkin_date = time.strftime(DEFAULT_SERVER_DATETIME_FORMAT)
        if not (checkout_date and checkin_date):
            return {'value': {}}
        delta = datetime.timedelta(days=1)
        dat_a = time.strptime(checkout_date,
                              DEFAULT_SERVER_DATETIME_FORMAT)[:5]
        addDays = datetime.datetime(*dat_a) + delta
        self.dummy = addDays.strftime(DEFAULT_SERVER_DATETIME_FORMAT)

    @api.onchange('partner_id')
    def onchange_partner_id(self):
        '''
        When you change partner_id it will update the partner_invoice_id,
        partner_shipping_id and pricelist_id of the hotel reservation as well
        ---------------------------------------------------------------------
        @param self: object pointer
        '''
        if not self.partner_id:
            self.partner_invoice_id = False
            self.partner_shipping_id = False
            self.partner_order_id = False
            self.partner_type = ''
            self.partner_discount = 0
        else:
            addr = self.partner_id.address_get(['delivery', 'invoice', 'contact'])
            self.partner_invoice_id = addr['invoice']
            self.partner_order_id = addr['contact']
            self.partner_shipping_id = addr['delivery']
            self.pricelist_id = self.partner_id.property_product_pricelist.id
            self.partner_type = self.partner_id.partner_type
            self.partner_discount = self.partner_id.partner_discount

    @api.multi
    def confirmed_reservation(self):
        """
        This method create a new recordset for hotel room reservation line
        ------------------------------------------------------------------
        @param self: The object pointer
        @return: new record set for hotel room reservation line.
        """
        reservation_line_obj = self.env['hotel.room.reservation.line']
        for reservation in self:
            self._cr.execute("select count(*) from hotel_reservation as hr "
                             "inner join hotel_reservation_line as hrl on \
                             hrl.line_id = hr.id "
                             "inner join hotel_reservation_line_room_rel as \
                             hrlrr on hrlrr.room_id = hrl.id "
                             "where (checkin,checkout) overlaps \
                             ( timestamp %s, timestamp %s ) "
                             "and hr.id <> cast(%s as integer) "
                             "and hr.state = 'confirm' "
                             "and hrlrr.hotel_reservation_line_id in ("
                             "select hrlrr.hotel_reservation_line_id \
                             from hotel_reservation as hr "
                             "inner join hotel_reservation_line as \
                             hrl on hrl.line_id = hr.id "
                             "inner join hotel_reservation_line_room_rel \
                             as hrlrr on hrlrr.room_id = hrl.id "
                             "where hr.id = cast(%s as integer) )",
                             (reservation.checkin, reservation.checkout,
                              str(reservation.id), str(reservation.id)))
            res = self._cr.fetchone()
            roomcount = res and res[0] or 0.0
            if roomcount:
                raise except_orm(_('Warning'), _('You tried to confirm \
                reservation with room those already reserved in this \
                reservation period'))
            else:
                for room_id in reservation.room_to_reserve:
                    vals = {
                        'room_id': room_id.id,
                        'check_in': reservation.checkin,
                        'check_out': reservation.checkout,
                        'state': 'assigned',
                        'reservation_id': reservation.id,
                        }
                    room_id.write({'isroom': False, 'status': 'occupied'})
                    reservation_line_obj.create(vals)
                self.write({'state': 'confirm'})
        return True

    @api.multi
    def cancel_reservation(self):
        """
        This method cancel recordset for hotel room reservation line
        ------------------------------------------------------------------
        @param self: The object pointer
        @return: cancel record set for hotel room reservation line.
        """
        room_res_line_obj = self.env['hotel.room.reservation.line']
        #hotel_res_line_obj = self.env['hotel_reservation.line']        
        room_reservation_line = room_res_line_obj.search([('reservation_id','in', self.ids)])
        room_reservation_line.unlink()
        #room_reservation_line.write({'state': 'unassigned'})
#         reservation_lines = hotel_res_line_obj.search([('line_id','in', self.ids)])
#         for reservation_line in reservation_lines:
#             reservation_line.reserve.write({'isroom': True, 'status': 'available'})
        return self.write({'state': 'cancel'})

    @api.multi
    def set_to_draft_reservation(self):
        self.write({'state':'draft'})
        # Deleting the existing instance of workflow for PO
        self.delete_workflow()
        self.create_workflow()   
        return True

    @api.multi
    def send_reservation_maill(self):
        '''
        This function opens a window to compose an email,
        template message loaded by default.
        @param self: object pointer
        '''
        assert len(self._ids) == 1, 'This is for a single id at a time.'
        ir_model_data = self.env['ir.model.data']
        try:
            template_id = (ir_model_data.get_object_reference
                           ('hotel_reservation',
                            'email_template_hotel_reservation')[1])
        except ValueError:
            template_id = False
        try:
            compose_form_id = (ir_model_data.get_object_reference
                               ('mail',
                                'email_compose_message_wizard_form')[1])
        except ValueError:
            compose_form_id = False
        ctx = dict()
        ctx.update({
            'default_model': 'hotel.reservation',
            'default_res_id': self._ids[0],
            'default_use_template': bool(template_id),
            'default_template_id': template_id,
            'default_composition_mode': 'comment',
            'force_send': True,
            'mark_so_as_sent': True
        })
        return {
            'type': 'ir.actions.act_window',
            'view_type': 'form',
            'view_mode': 'form',
            'res_model': 'mail.compose.message',
            'views': [(compose_form_id, 'form')],
            'view_id': compose_form_id,
            'target': 'new',
            'context': ctx,
            'force_send': True
        }

    @api.model
    def reservation_reminder_24hrs(self):
        """
        This method is for scheduler
        every 1day scheduler will call this method to
        find all tomorrow's reservations.
        ----------------------------------------------
        @param self: The object pointer
        @return: send a mail
        """
        now_str = time.strftime(DEFAULT_SERVER_DATETIME_FORMAT)
        now_date = datetime.datetime.strptime(now_str,
                                              DEFAULT_SERVER_DATETIME_FORMAT)
        ir_model_data = self.env['ir.model.data']
        template_id = (ir_model_data.get_object_reference
                       ('hotel_reservation',
                        'email_template_reservation_reminder_24hrs')[1])
        template_rec = self.env['email.template'].browse(template_id)
        for travel_rec in self.search([]):
            checkin_date = (datetime.datetime.strptime
                            (travel_rec.checkin,
                             DEFAULT_SERVER_DATETIME_FORMAT))
            difference = relativedelta(now_date, checkin_date)
            if(difference.days == -1 and travel_rec.partner_id.email and
               travel_rec.state == 'confirm'):
                template_rec.send_mail(travel_rec.id, force_send=True)
        return True

    @api.multi
    def _create_folio(self):
        """
        This method is for create new hotel folio.
        -----------------------------------------
        @param self: The object pointer
        @return: new record set for hotel folio.
        """
        hotel_folio_obj = self.env['hotel.folio']
        room_obj = self.env['hotel.room']
        for reservation in self:
            folio_lines = []
            service_lines = []
            checkin_date = reservation['checkin']
            checkout_date = reservation['checkout']
            if not self.checkin < self.checkout:
                raise except_orm(_('Error'),
                                 _('Checkout date should be greater \
                                 than the Checkin date.'))
            duration_vals = (self.onchange_check_dates
                             (checkin_date=checkin_date,
                              checkout_date=checkout_date, duration=False))
            duration = duration_vals.get('duration') or 0.0
            folio_vals = {
                'date_order': reservation.date_order,
                'warehouse_id': reservation.warehouse_id.id,
                'partner_id': reservation.partner_id.id,
                'pricelist_id': reservation.pricelist_id.id,
                'partner_invoice_id': reservation.partner_invoice_id.id,
                'partner_shipping_id': reservation.partner_shipping_id.id,
                'checkin_date': reservation.checkin,
                'checkout_date': reservation.checkout,
                'duration': duration,
                'reservation_id': reservation.id,
                'partner_type': reservation.partner_type,
                'partner_discount': reservation.partner_discount,
                'service_lines': reservation['folio_id']
            }
            date_a = (datetime.datetime(*time.strptime(reservation['checkout'],DEFAULT_SERVER_DATETIME_FORMAT)[:5]))
            date_b = (datetime.datetime(*time.strptime(reservation['checkin'],DEFAULT_SERVER_DATETIME_FORMAT)[:5]))
            #FOR ROOM & SERVICE IN PACKAGE
            for pline in reservation.reservation_package_line:
                if pline.reserve_room:
                    #print "==reserve_room==",[x.id for x in pline.tax_id]
                    rprod_uom = pline.reserve_room.product_id and pline.reserve_room.product_id.uom_id.id
                    price_unit_room = pline.price_room                
                    folio_lines.append((0, 0, {
                        'name': 'PCKG:'+reservation['reservation_no'],
                        'checkin_date': checkin_date,
                        'checkout_date': checkout_date,
                        'product_id': pline.reserve_room.product_id and pline.reserve_room.product_id.id,
                        'product_uom_qty': pline.quantity,#((date_a - date_b).days) + 1,
                        'product_uom': rprod_uom,
                        'price_unit': price_unit_room,
                        'discount': pline.discount,
                        'partner_discount': reservation.partner_discount,
                        'tax_id': [(6, 0, [x.id for x in pline.tax_id])],
                        'type': pline.type,
                        'is_reserved': True}))
                if pline.reserve_ser:
                    sprod_uom = pline.reserve_ser.service_id and pline.reserve_ser.service_id.uom_id.id
                    price_unit_service = pline.price_service
                    service_lines.append((0, 0, {
                        'name': 'PCKG:'+reservation['reservation_no'],
                        'checkin_date': checkin_date,
                        'checkout_date': checkout_date,
                        'product_id': pline.reserve_ser.service_id and pline.reserve_ser.service_id.id,
                        'product_uom_qty': pline.quantity,#((date_a - date_b).days) + 1,
                        'product_uom': sprod_uom,
                        'price_unit': price_unit_service,
                        'discount': pline.discount,
                        'partner_discount': reservation.partner_discount,
                        'tax_id': [(6, 0, [x.id for x in pline.tax_id])],
                        'type': pline.type,
                        'is_reserved': True}))
                res_obj = room_obj.browse([pline.reserve_room.id])
                res_obj.write({'status': 'occupied', 'isroom': False})
            #FOR ROOM ONLY
            for rline in reservation.reservation_room_line:
                rprod_uom = rline.room_id.product_id and rline.room_id.product_id.uom_id.id
                rprice_unit = rline.price_unit
                folio_lines.append((0, 0, {
                    'name': 'ROOM:'+reservation['reservation_no'],
                    'checkin_date': checkin_date,
                    'checkout_date': checkout_date,
                    'product_id': rline.room_id.product_id and rline.room_id.product_id.id,
                    'product_uom_qty': rline.quantity,#((date_a - date_b).days) + 1,
                    'product_uom': rprod_uom,
                    'price_unit': rprice_unit,
                    'discount': rline.discount,
                    'partner_discount': reservation.partner_discount,
                    'tax_id': [(6, 0, [x.id for x in rline.tax_id])],
                    'type': rline.type,
                    'is_reserved': True}))
                res_obj = room_obj.browse([rline.room_id.id])
                res_obj.write({'status': 'occupied', 'isroom': False})
            #FOR SERVICE ONLY
            for sline in reservation.reservation_service_line:
                sprod_uom = sline.service_id.service_id and sline.service_id.service_id.uom_id.id
                sprice_unit = sline.price_unit
                service_lines.append((0, 0, {
                    'name': 'SVR:'+reservation['reservation_no'],
                    'checkin_date': checkin_date,
                    'checkout_date': checkout_date,
                    'product_id': sline.service_id.service_id and sline.service_id.service_id.id,
                    'product_uom_qty': sline.quantity,#((date_a - date_b).days) + 1,
                    'product_uom': sprod_uom,
                    'price_unit': sprice_unit,
                    'discount': sline.discount,
                    'partner_discount': reservation.partner_discount,
                    'tax_id': [(6, 0, [x.id for x in sline.tax_id])],
                    'type': sline.type,
                    'is_reserved': True}))
                #res_obj = room_obj.browse([line.room_id.id])
                #res_obj.write({'status': 'occupied', 'isroom': False})
            folio_vals.update({'room_lines': folio_lines, 'service_lines': service_lines})
            folio = hotel_folio_obj.create(folio_vals)
            self._cr.execute('insert into hotel_folio_reservation_rel (order_id, invoice_id) values (%s,%s)',(reservation.id, folio.id))
            reservation.write({'state': 'done'})
        return True

    @api.multi
    def onchange_check_dates(self, checkin_date=False, checkout_date=False,
                             duration=False):
        '''
        This mathod gives the duration between check in checkout if
        customer will leave only for some hour it would be considers
        as a whole day. If customer will checkin checkout for more or equal
        hours, which configured in company as additional hours than it would
        be consider as full days
        --------------------------------------------------------------------
        @param self: object pointer
        @return: Duration and checkout_date
        '''
        value = {}
        company_obj = self.env['res.company']
        configured_addition_hours = 0
        company_ids = company_obj.search([])
        if company_ids.ids:
            configured_addition_hours = company_ids[0].additional_hours
        duration = 0
        if checkin_date and checkout_date:
            chkin_dt = (datetime.datetime.strptime
                        (checkin_date, DEFAULT_SERVER_DATETIME_FORMAT))
            chkout_dt = (datetime.datetime.strptime
                         (checkout_date, DEFAULT_SERVER_DATETIME_FORMAT))
            dur = chkout_dt - chkin_dt
            duration = dur.days + 1
            if configured_addition_hours > 0:
                additional_hours = abs((dur.seconds / 60) / 60)
                if additional_hours >= configured_addition_hours:
                    duration += 1
        value.update({'duration': duration})
        return value

    @api.model
    def create(self, vals):
        """
        Overrides orm create method.
        @param self: The object pointer
        @param vals: dictionary of fields value.
        """
        if not vals:
            vals = {}
        if self._context is None:
            self._context = {}
        vals['reservation_no'] = self.env['ir.sequence'
                                          ].get('hotel.reservation')
        return super(HotelReservation, self).create(vals)

class HotelReservationLine(models.Model):
    _name = "hotel_reservation.line"
    _description = "Reservation Line"

    name = fields.Char(related='reserve.name', string='Name', size=64)
    line_id = fields.Many2one('hotel.reservation')
    reserve = fields.Many2many('hotel.room',
                               'hotel_reservation_line_room_rel',
                               'hotel_reservation_line_id', 'room_id',
                               domain="[('isroom','=',True)]")
    categ_id = fields.Many2one('product.category', 'Room Type',
                               domain="[('isroomtype','=',True)]",
                               change_default=True)
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.user.company_id)
    
#     @api.onchange('line_id.reservation_package_line', 'line_id.reservation_package_line.package_id', 'line_id.reservation_package_line.reserve_room')
#     def onchange_room_id(self):
#         #if self.line_id.reservation_package_line:
#         self.reserve = self.line_id.package_id.room_id
#         print "==onchange_room_id==",self.line_id.package_id.room_id
            
    @api.onchange('categ_id')
    def on_change_categ(self):
        '''
        When you change categ_id it check checkin and checkout are
        filled or not if not then raise warning
        -----------------------------------------------------------
        @param self: object pointer
        '''
        hotel_room_obj = self.env['hotel.room']
        hotel_room_ids = hotel_room_obj.search([('categ_id', '=', self.categ_id.id)])
        room_ids = []
        if not self.line_id.checkin:
            raise except_orm(_('Warning'),
                             _('Before choosing a room,\n You have to select \
                             a Check in date or a Check out date in \
                             the reservation form.'))
        for room in hotel_room_ids:
            assigned = False
            for line in room.room_reservation_line_ids:
                if line.status != 'cancel':
                    if (line.check_in <= self.line_id.checkin <=
                        line.check_out) or (line.check_in <=
                                            self.line_id.checkout <=
                                            line.check_out):
                        assigned = True
            for rm_line in room.room_line_ids:
                if rm_line.status != 'cancel':
                    if (rm_line.check_in <= self.line_id.checkin <=
                        rm_line.check_out) or (rm_line.check_in <=
                                            self.line_id.checkout <=
                                            rm_line.check_out):
                        assigned = True
            if not assigned:
                room_ids.append(room.id)
        domain = {'reserve': [('id', 'in', room_ids)]}
        return {'domain': domain}

    @api.multi
    def unlink(self):
        """
        Overrides orm unlink method.
        @param self: The object pointer
        @return: True/False.
        """
        hotel_room_reserv_line_obj = self.env['hotel.room.reservation.line']
        for reserv_rec in self:
            for rec in reserv_rec.reserve:
                hres_arg = [('room_id', '=', rec.id),
                            ('reservation_id', '=', reserv_rec.line_id.id)]
                myobj = hotel_room_reserv_line_obj.search(hres_arg)
                if myobj.ids:
                    rec.write({'isroom': True, 'status': 'available'})
                    myobj.unlink()
        return super(HotelReservationLine, self).unlink()

# class HotelReservationLine2(models.Model):
#     _name = "hotel_reservation.line2"
#     _description = "Reservation Line2"
# 
#     name = fields.Char(related='reserve.name', string='Name', size=64)
#     line_id = fields.Many2one('hotel.reservation')
#     reserve = fields.Many2many('hotel.services',
#                                'hotel_reservation_line_room_rel2',
#                                'hotel_reservation_line_id2', 'service_id',
#                                domain="[('isservice','=',True),\
#                                ('categ_id','=',categ_id)]")
#     categ_id = fields.Many2one('product.category', 'Service Type',
#                                domain="[('isservicetype','=',True)]",
#                                change_default=True)
#     company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.user.company_id)

class HotelReservationPackageLine(models.Model):
    _name = "hotel_reservation.package.line"
    _description = "Reservation Package Line"
            
    @api.depends('line_id.duration', 'line_id.checkin', 'line_id.checkout', 
                'package_id', 'price_unit', 'discount', 'partner_discount', 'quantity', 'tax_id',
                'line_id.pricelist_id', 'line_id.pricelist_id.currency_id', 'line_id.company_id')
    def _compute_price(self):
        for line in self:
            price = line.price_unit
            if line.type == 'child':
                price = line.price_unit * (1 - (line.discount or 0.0) / 100.0)
            price = price * (1 - (line.partner_discount or 0.0) / 100.0)
            taxes = line.tax_id.compute_all(price, line.quantity*line.line_id.duration, product=line.package_id.package_id, partner=line.line_id.partner_id)
            price_tax = 0.0
            if taxes['taxes']:
                price_tax = taxes['taxes'][0]['amount']
            line.update({
                'price_subtotal': line.line_id.pricelist_id.currency_id.round(taxes['total']),
                'price_tax': line.line_id.pricelist_id.currency_id.round(price_tax),
            })
        
    name = fields.Char('Name', size=64)
    line_id = fields.Many2one('hotel.reservation')
    package_id = fields.Many2one('hotel.package', 'Package')
    #product_id = fields.Many2one('product.product', related='package_id.package_id', string='Product')
    price_unit = fields.Float('Price/Rate')
    price_room = fields.Float('Price Room', related='package_id.list_price', readonly=True)
    price_service = fields.Float('Price Service', related='package_id.list_price2', readonly=True)
    quantity = fields.Float('Pax', digits=dp.get_precision('Product UoS'), default=1.0)
    discount = fields.Float('Disc (%)', digits= dp.get_precision('Discount'))
    partner_discount = fields.Float('Disc Cust. (%)', related='line_id.partner_discount', digits= dp.get_precision('Discount'))
    tax_id = fields.Many2many('account.tax', string='Taxes', domain=['|', ('active', '=', False), ('active', '=', True)])
    
    price_subtotal = fields.Float(compute='_compute_price', string='Subtotal', readonly=True, store=True)
    price_discount = fields.Float(compute='_compute_price', string='Disc', readonly=True, store=True)
    price_tax = fields.Float(compute='_compute_price', string='Taxes', readonly=True, store=True)
    
    type = fields.Selection([('adult','Adult'),('child','Child')], string='Adult/Child', default='adult')
    categ_id = fields.Many2one('product.category', string='Room Type', related='package_id.categ_id2', readonly=True, store=True)
    #package_room_line = fields.One2many('package.room.line', 'package_id', string='Room')
    #package_service_line = fields.One2many('package.service.line', 'package_id', string='Room')
    reserve_room = fields.Many2one('hotel.room', string='Room', domain="[('isroom','=',True),('categ_id','=',categ_id)]")
#     reserve_room = fields.Many2many('hotel.room',
#                                'hotel_reservation_package_line_room_rel',
#                                'hotel_reservation_package_line_id', 'room_id',
#                                domain="[('isroom','=',True),('categ_id','=',categ_id)]")
    categ_id2 = fields.Many2one('product.category', string='Service Type', related='package_id.categ_id3', readonly=True, store=True)
    reserve_ser = fields.Many2one('hotel.services', string='Service', domain="[('isservice','=',True),('categ_id','=',categ_id2)]")
#     reserve_ser = fields.Many2many('hotel.services',
#                                'hotel_reservation_services_line_rel',
#                                'hotel_reservation_service_line_id', 'ser_id',
#                                domain="[('isservice','=',True),('categ_id','=',categ_id2)]")
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.user.company_id)
    
    @api.onchange('package_id')
    def onchange_package_id(self):
        if self.package_id:
            self.price_unit = self.package_id.package_price
            #self.price_room = self.package_id.list_price
            #self.price_service = self.package_id.list_price2
            #self.reserve_room = self.package_id.room_id
            #self.reserve_ser = self.package_id.service_id
#             print "======",self.line_id.reservation_line.reserve,self.reserve_room,self.package_id.room_id
#             self.line_id.reservation_line.reserve = self.package_id.room_id
    
#     
# class PackageRoomLine(models.Model):
#     _name = "package.room.line"
#     _description = "Package Room Line"
#     
#     package_id = fields.Many2one('hotel_reservation.package.line', string='Package')
#     room_id = fields.Many2one('hotel.room', 'Room', domain="[('isroom','=',True),('categ_id','=',package_id.categ_id)]")
#     price_normal = fields.Float(string='Normal Price')
#     price_package = fields.Float(string='Package Price')
#     
# class PackageServiceLine(models.Model):
#     _name = "package.service.line"
#     _description = "Package Service Line"
#     
#     package_id = fields.Many2one('hotel_reservation.package.line', string='Package')
#     service_id = fields.Many2one('hotel.services', 'Service', domain="[('isservice','=',True),('categ_id','=',package_id.categ_id2)]")
#     price_normal = fields.Float(string='Normal Price')
#     price_package = fields.Float(string='Package Price')
    
class HotelReservationRoomLine(models.Model):
    _name = "hotel_reservation.room.line"
    _description = "Reservation Room Line"

    @api.depends('line_id.duration', 'price_unit', 'discount', 'partner_discount', 'quantity', 'tax_id',
        'line_id.pricelist_id', 'line_id.pricelist_id.currency_id', 'line_id.company_id')
    def _compute_room_price(self):
        for line in self:
            price = line.price_unit
            if line.type == 'child':
                price = line.price_unit * (1 - (line.discount or 0.0) / 100.0)
            price = price * (1 - (line.partner_discount or 0.0) / 100.0)
            taxes = line.tax_id.compute_all(price, line.quantity*line.line_id.duration, product=line.room_id.product_id, partner=line.line_id.partner_id)
            price_tax = 0.0
            if taxes['taxes']:
                price_tax = taxes['taxes'][0]['amount']
            line.update({
                'price_subtotal': line.line_id.pricelist_id.currency_id.round(taxes['total']),
                'price_tax': line.line_id.pricelist_id.currency_id.round(price_tax),
            })
            
    name = fields.Char('Service', size=64)
    line_id = fields.Many2one('hotel.reservation')
    categ_id = fields.Many2one('product.category', 'Room Type', domain="[('isroomtype','=',True)]", change_default=True)
    room_id = fields.Many2one('hotel.room', 'Room', domain="[('isroom','=',True),('categ_id','=',categ_id)]")
    price_unit = fields.Float('Price/Rate')
    quantity = fields.Float('Pax', digits=dp.get_precision('Product UoS'), default=1.0)
    discount = fields.Float('Disc (%)', digits= dp.get_precision('Discount'))
    partner_discount = fields.Float('Disc Cust. (%)', related='line_id.partner_discount', digits= dp.get_precision('Discount'))
    tax_id = fields.Many2many('account.tax', string='Taxes', domain=['|', ('active', '=', False), ('active', '=', True)])
    
    price_subtotal = fields.Float(compute='_compute_room_price', string='Subtotal', readonly=True, store=True)
    price_tax = fields.Float(compute='_compute_room_price', string='Taxes', readonly=True, store=True)
    #price_total = fields.Float(compute='_compute_room_price', string='Total', readonly=True, store=True)

    type = fields.Selection([('adult','Adult'),('child','Child')], string='Adult/Child', default='adult')
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.user.company_id)
    
    @api.onchange('room_id')
    def onchange_room_id(self):
        if self.room_id:
            self.price_unit = self.room_id.list_price
            
class HotelReservationServiceLine(models.Model):
    _name = "hotel_reservation.service.line"
    _description = "Reservation Service Line"

    @api.depends('line_id.duration', 'price_unit', 'discount', 'partner_discount', 'quantity',
        'line_id.pricelist_id', 'line_id.pricelist_id.currency_id', 'line_id.company_id')
    def _compute_service_price(self):
        for line in self:
            price = line.price_unit
            if line.type == 'child':
                price = line.price_unit * (1 - (line.discount or 0.0) / 100.0)
            price = price * (1 - (line.partner_discount or 0.0) / 100.0)
            taxes = line.tax_id.compute_all(price, line.quantity*line.line_id.duration, product=line.service_id.service_id, partner=line.line_id.partner_id)
            price_tax = 0.0
            if taxes['taxes']:
                price_tax = taxes['taxes'][0]['amount']
            line.update({
                'price_subtotal': line.line_id.pricelist_id.currency_id.round(taxes['total']),
                'price_tax': line.line_id.pricelist_id.currency_id.round(price_tax),
            })

        
    name = fields.Char('Service', size=64)
    line_id = fields.Many2one('hotel.reservation')
    categ_id = fields.Many2one('product.category', 'Service Type', domain="[('isservicetype','=',True)]", change_default=True)
    service_id = fields.Many2one('hotel.services', 'Service', domain="[('isservice','=',True),('categ_id','=',categ_id)]")
    price_unit = fields.Float('Price/Rate')
    quantity = fields.Float('Pax', digits=dp.get_precision('Product UoS'), default=1.0)
    discount = fields.Float('Disc (%)', digits= dp.get_precision('Discount'))
    partner_discount = fields.Float('Disc Cust. (%)', related='line_id.partner_discount', digits= dp.get_precision('Discount'))
    tax_id = fields.Many2many('account.tax', string='Taxes', domain=['|', ('active', '=', False), ('active', '=', True)])
    
    price_subtotal = fields.Float(compute='_compute_service_price', string='Subtotal', readonly=True, store=True)
    price_tax = fields.Float(compute='_compute_service_price', string='Taxes', readonly=True, store=True)
    #price_total = fields.Float(compute='_compute_service_price', string='Total', readonly=True, store=True)
    
    type = fields.Selection([('adult','Adult'),('child','Child')], string='Adult/Child', default='adult')
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.user.company_id)
    
    @api.onchange('service_id')
    def onchange_service_id(self):
        if self.service_id:
            self.price_unit = self.service_id.list_price
            
class HotelRoomReservationLine(models.Model):
    _name = 'hotel.room.reservation.line'
    _description = 'Hotel Room Reservation'
    _rec_name = 'room_id'
    
    room_id = fields.Many2one(comodel_name='hotel.room', string='Room')
    check_in = fields.Datetime('Check In Date', required=True)
    check_out = fields.Datetime('Check Out Date', required=True)
    state = fields.Selection([('assigned', 'Assigned'),
                              ('unassigned', 'Unassigned')], 'Room Status')
    reservation_id = fields.Many2one('hotel.reservation', string='Reservation')
    status = fields.Selection(string='state', related='reservation_id.state')


class HotelRoom(models.Model):
    _inherit = 'hotel.room'
    _description = 'Hotel Room'

    room_reservation_line_ids = fields.One2many('hotel.room.reservation.line', 'room_id', string='Room Reserv Line')

    @api.model
    def cron_room_line(self):
        """
        This method is for scheduler
        every 1min scheduler will call this method and check Status of
        room is occupied or available
        --------------------------------------------------------------
        @param self: The object pointer
        @return: update status of hotel room reservation line
        """
        reservation_line_obj = self.env['hotel.room.reservation.line']
        folio_room_line_obj = self.env['folio.room.line']
        now = datetime.datetime.now()
        curr_date = now.strftime(DEFAULT_SERVER_DATETIME_FORMAT)
        for room in self.search([]):
            reserv_line_ids = [reservation_line.ids for
                               reservation_line in
                               room.room_reservation_line_ids]
            reserv_args = [('id', 'in', reserv_line_ids),
                           ('check_in', '<=', curr_date),
                           ('check_out', '>=', curr_date)]
            reservation_line_ids = reservation_line_obj.search(reserv_args)
            rooms_ids = [room_line.ids for room_line in room.room_line_ids]
            rom_args = [('id', 'in', rooms_ids),
                        ('check_in', '<=', curr_date),
                        ('check_out', '>=', curr_date)]
            room_line_ids = folio_room_line_obj.search(rom_args)
            status = {'isroom': True, 'color': 5}
            if reservation_line_ids.ids:
                status = {'isroom': False, 'color': 2}
            room.write(status)
            if room_line_ids.ids:
                status = {'isroom': False, 'color': 2}
            room.write(status)
            if reservation_line_ids.ids and room_line_ids.ids:
                raise except_orm(_('Wrong Entry'),
                                 _('Please Check Rooms Status \
                                 for %s.' % (room.name)))
        return True


class RoomReservationSummary(models.Model):

    _name = 'room.reservation.summary'
    _description = 'Room reservation summary'

    date_from = fields.Datetime('Date From')
    date_to = fields.Datetime('Date To')
    company_id = fields.Many2one('res.company', string='Location', required=True, default=lambda self: self.env.user.company_id)
    summary_header = fields.Text('Summary Header')
    room_summary = fields.Text('Room Summary')

    @api.model
    def default_get(self, fields):
        """
        To get default values for the object.
        @param self: The object pointer.
        @param fields: List of fields for which we want default values
        @return: A dictionary which of fields with values.
        """
        if self._context is None:
            self._context = {}
        res = super(RoomReservationSummary, self).default_get(fields)
        # Added default datetime as today and date to as today + 30.
        from_dt = datetime.date.today()
        dt_from = from_dt.strftime(DEFAULT_SERVER_DATETIME_FORMAT)
        to_dt = from_dt + relativedelta(days=30)
        dt_to = to_dt.strftime(DEFAULT_SERVER_DATETIME_FORMAT)
        res.update({'date_from': dt_from, 'date_to': dt_to})

        if not self.date_from and self.date_to:
            date_today = datetime.datetime.today()
            first_day = datetime.datetime(date_today.year,
                                          date_today.month, 1, 0, 0, 0)
            first_temp_day = first_day + relativedelta(months=1)
            last_temp_day = first_temp_day - relativedelta(days=1)
            last_day = datetime.datetime(last_temp_day.year,
                                         last_temp_day.month,
                                         last_temp_day.day, 23, 59, 59)
            date_froms = first_day.strftime(DEFAULT_SERVER_DATETIME_FORMAT)
            date_ends = last_day.strftime(DEFAULT_SERVER_DATETIME_FORMAT)
            res.update({'date_from': date_froms, 'date_to': date_ends})
        return res

    @api.multi
    def room_reservation(self):
        '''
        @param self: object pointer
        '''
        mod_obj = self.env['ir.model.data']
        if self._context is None:
            self._context = {}
        model_data_ids = mod_obj.search([('model', '=', 'ir.ui.view'),
                                         ('name', '=',
                                          'view_hotel_reservation_form')])
        resource_id = model_data_ids.read(fields=['res_id'])[0]['res_id']
        return {'name': _('Reconcile Write-Off'),
                'context': self._context,
                'view_type': 'form',
                'view_mode': 'form',
                'res_model': 'hotel.reservation',
                'views': [(resource_id, 'form')],
                'type': 'ir.actions.act_window',
                'target': 'new',
                }

    @api.onchange('date_from', 'date_to', 'company_id')
    def get_room_summary(self):
        '''
        @param self: object pointer
         '''
        res = {}
        all_detail = []
        room_obj = self.env['hotel.room']
        reservation_line_obj = self.env['hotel.room.reservation.line']
        folio_room_line_obj = self.env['folio.room.line']
        date_range_list = []
        main_header = []
        summary_header_list = ['Rooms']
        if self.date_from and self.date_to:
            if self.date_from > self.date_to:
                raise except_orm(_('User Error!'),
                                 _('Please Check Time period Date \
                                 From can\'t be greater than Date To !'))
            d_frm_obj = (datetime.datetime.strptime
                         (self.date_from, DEFAULT_SERVER_DATETIME_FORMAT))
            d_to_obj = (datetime.datetime.strptime
                        (self.date_to, DEFAULT_SERVER_DATETIME_FORMAT))
            temp_date = d_frm_obj
            while(temp_date <= d_to_obj):
                val = ''
                val = (str(temp_date.strftime("%a")) + ' ' +
                       str(temp_date.strftime("%b")) + ' ' +
                       str(temp_date.strftime("%d")))
                summary_header_list.append(val)
                date_range_list.append(temp_date.strftime(DEFAULT_SERVER_DATETIME_FORMAT))
                temp_date = temp_date + datetime.timedelta(days=1)
            all_detail.append(summary_header_list)
            room_ids = room_obj.search([('company_id','=',self.company_id.id)])
            #print "====room_ids===",room_ids,self.env.user.company_id.id
            all_room_detail = []
            for room in room_ids:
                room_detail = {}
                room_list_stats = []
                room_detail.update({'name': room.name or ''})
                if not room.room_reservation_line_ids and \
                   not room.room_line_ids:
                    for chk_date in date_range_list:
                        room_list_stats.append({'state': 'Free',
                                                'date': chk_date})
                else:
                    for chk_date in date_range_list:
                        reserline_ids = room.room_reservation_line_ids.ids
                        reservline_ids = (reservation_line_obj.search
                                          ([('id', 'in', reserline_ids),
                                            ('check_in', '<=', chk_date),
                                            ('check_out', '>=', chk_date),
                                            ('status', 'not in', ('draft','cancel'))
                                            ]))
                        fol_room_line_ids = room.room_line_ids.ids
                        chk_state = ['draft', 'cancel']
                        folio_resrv_ids = (folio_room_line_obj.search
                                           ([('id', 'in', fol_room_line_ids),
                                             ('check_in', '<=', chk_date),
                                             ('check_out', '>=', chk_date),
                                             ('status', 'not in', chk_state)
                                             ]))
                        if reservline_ids or folio_resrv_ids:
                            room_list_stats.append({'state': reservline_ids and reservline_ids[0].reservation_id.partner_id.name or 'Reserved',
                                                    'date': chk_date,
                                                    'room_id': room.id,
                                                    'is_draft': 'No',
                                                    'data_model': '',
                                                    'data_id': 0})
                        else:
                            room_list_stats.append({'state': 'Free',
                                                    'date': chk_date,
                                                    'room_id': room.id})

                room_detail.update({'value': room_list_stats})
                all_room_detail.append(room_detail)
            main_header.append({'header': summary_header_list})
            self.summary_header = str(main_header)
            self.room_summary = str(all_room_detail)
        return res


class QuickRoomReservation(models.TransientModel):
    _name = 'quick.room.reservation'
    _description = 'Quick Room Reservation'

    partner_id = fields.Many2one('res.partner', string="Customer",
                                 required=True)
    check_in = fields.Datetime('Check In', required=True)
    check_out = fields.Datetime('Check Out', required=True)
    room_id = fields.Many2one('hotel.room', 'Room', required=True)
    warehouse_id = fields.Many2one('stock.warehouse', 'Hotel', required=True)
    pricelist_id = fields.Many2one('product.pricelist', 'pricelist',
                                   required=True)
    partner_invoice_id = fields.Many2one('res.partner', 'Invoice Address',
                                         required=True)
    partner_order_id = fields.Many2one('res.partner', 'Ordering Contact',
                                       required=True)
    partner_shipping_id = fields.Many2one('res.partner', 'Delivery Address',
                                          required=True)

    @api.onchange('check_out', 'check_in')
    def on_change_check_out(self):
        '''
        When you change checkout or checkin it will check whether
        Checkout date should be greater than Checkin date
        and update dummy field
        -----------------------------------------------------------
        @param self: object pointer
        @return: raise warning depending on the validation
        '''
        if self.check_out and self.check_in:
            if self.check_out < self.check_in:
                raise except_orm(_('Warning'),
                                 _('Checkout date should be greater \
                                 than Checkin date.'))

    @api.onchange('partner_id')
    def onchange_partner_id_res(self):
        '''
        When you change partner_id it will update the partner_invoice_id,
        partner_shipping_id and pricelist_id of the hotel reservation as well
        ---------------------------------------------------------------------
        @param self: object pointer
        '''
        if not self.partner_id:
            self.partner_invoice_id = False
            self.partner_shipping_id = False
            self.partner_order_id = False
        else:
            addr = self.partner_id.address_get(['delivery', 'invoice',
                                                'contact'])
            self.partner_invoice_id = addr['invoice']
            self.partner_order_id = addr['contact']
            self.partner_shipping_id = addr['delivery']
            self.pricelist_id = self.partner_id.property_product_pricelist.id

    @api.model
    def default_get(self, fields):
        """
        To get default values for the object.
        @param self: The object pointer.
        @param fields: List of fields for which we want default values
        @return: A dictionary which of fields with values.
        """
        if self._context is None:
            self._context = {}
        res = super(QuickRoomReservation, self).default_get(fields)
        if self._context:
            keys = self._context.keys()
            if 'date' in keys:
                res.update({'check_in': self._context['date']})
            if 'room_id' in keys:
                roomid = self._context['room_id']
                res.update({'room_id': int(roomid)})
        return res

    @api.multi
    def room_reserve(self):
        """
        This method create a new record for hotel.reservation
        -----------------------------------------------------
        @param self: The object pointer
        @return: new record set for hotel reservation.
        """
        hotel_res_obj = self.env['hotel.reservation']
        for res in self:
            rec = (hotel_res_obj.create
                   ({'partner_id': res.partner_id.id,
                     'partner_invoice_id': res.partner_invoice_id.id,
                     'partner_order_id': res.partner_order_id.id,
                     'partner_shipping_id': res.partner_shipping_id.id,
                     'checkin': res.check_in,
                     'checkout': res.check_out,
                     'warehouse_id': res.warehouse_id.id,
                     'pricelist_id': res.pricelist_id.id,
                     'reservation_line': [(0, 0,
                                           {'reserve': [(6, 0,
                                                         [res.room_id.id])],
                                            'name': (res.room_id and
                                                     res.room_id.name or '')
                                            })]
                     }))
        return rec
