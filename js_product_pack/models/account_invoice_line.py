# -*- encoding: utf-8 -*-
##############################################################################
# For copyright and license notices, see __openerp__.py file in root directory
##############################################################################
from openerp import fields, models, api, _
from openerp.exceptions import Warning

class account_invoice_line(models.Model):
    _inherit = 'account.invoice.line'

    # Fields for sale order pack
    pack_total = fields.Float(
        string='Pack total',
        compute='_get_pack_total'
        )
    pack_line_ids = fields.One2many(
        'account.invoice.line.pack.line',
        'invoice_line_id',
        'Pack Lines'
        )
    pack_type = fields.Selection(
        related='product_id.pack_price_type',
        readonly=True
        )

    # Fields for common packs
    pack_depth = fields.Integer(
        'Depth',
        help='Depth of the product if it is part of a pack.'
    )
    pack_parent_line_id = fields.Many2one(
        'account.invoice.line',
        'Pack',
        help='The pack that contains this product.',
        ondelete="cascade",
        # copy=False,
    )
    pack_child_line_ids = fields.One2many(
        'account.invoice.line',
        'pack_parent_line_id',
        'Lines in pack'
    )

    @api.one
    @api.constrains('product_id', 'price_unit', 'product_qty')
    def expand_pack_invoice_line(self):
        detailed_packs = ['components_price', 'totalice_price', 'fixed_price']
        if (self.invoice_id.state == 'draft' and
                self.product_id.pack and
                self.pack_type in detailed_packs):
            for subline in self.product_id.pack_line_ids:
                vals = subline.get_account_invoice_line_vals(
                    self, self.invoice_id)
                vals['sequence'] = self.sequence
                existing_subline = self.search([
                    ('product_id', '=', subline.product_id.id),
                    ('pack_parent_line_id', '=', self.id),
                    ], limit=1)
                # if subline already exists we update, if not we create
                if existing_subline:
                    existing_subline.write(vals)
                else:
                    self.create(vals)

    @api.multi
    def button_save_data(self):
        return True

    @api.multi
    def action_pack_detail(self):
        view_id = self.env['ir.model.data'].xmlid_to_res_id(
            'js_product_pack.view_invoice_line_form2')
        view = {
            'name': _('Details'),
            'view_type': 'form',
            'view_mode': 'form',
            'res_model': 'account.invoice.line',
            'view_id': view_id,
            'type': 'ir.actions.act_window',
            'target': 'new',
            'readonly': True,
            'res_id': self.id,
            'context': self.env.context
        }
        return view

    @api.one
    @api.depends(
        'pack_line_ids',
        'pack_line_ids.price_subtotal',
    )
    def _get_pack_total(self):
        pack_total = 0.0
        if self.pack_line_ids:
            pack_total = sum(x.price_subtotal for x in self.pack_line_ids)
        self.pack_total = pack_total
# 
    @api.one
    @api.onchange('pack_total')
    def _onchange_pack_line_ids(self):
        self.price_unit = self.pack_total

    @api.constrains('product_id')
    def expand_inv_line_none_detailed_pack(self):
        if self.product_id.pack_price_type == 'none_detailed_assited_price':
            # remove previus existing lines
            self.pack_line_ids.unlink()

            # create a sale pack line for each product pack line
            account_id = False
            for pack_line in self.product_id.pack_line_ids:
                price_unit = pack_line.product_id.lst_price
                quantity = pack_line.quantity
                if not account_id:
                    if pack_line.product_id:
                        account_id = pack_line.product_id.property_account_income.id
                        if not account_id:
                            account_id = pack_line.product_id.categ_id.property_account_income_categ.id
                        if not account_id:
                            raise Warning(_(
                                'Error!\n'
                                'Please define income account for this product: "%s" (id:%d).: %s') % (pack_line.product_id.name, pack_line.product_id.id,))
                vals = {
                    'invoice_line_id': self.id,
                    'product_id': pack_line.product_id.id,
                    'account_id': account_id,
                    'product_uom_qty': quantity,
                    'price_unit': price_unit,
                    'discount': pack_line.discount,
                    'price_subtotal': price_unit * quantity,
                    }
                self.pack_line_ids.create(vals)
                
                
    
    @api.model
    def move_line_get(self, invoice_id):
        inv = self.env['account.invoice'].browse(invoice_id)
        currency = inv.currency_id.with_context(date=inv.date_invoice)
        company_currency = inv.company_id.currency_id

        res = []
        for line in inv.invoice_line:
            if line.product_id.pack_price_type == 'none_detailed_assited_price':
                for pack_line in line.pack_line_ids:
                    mres = self.move_line_pack_get_item(pack_line)
                    mres['invl_id'] = line.id
                    res.append(mres)
                    tax_code_found = False
                    taxes = line.invoice_line_tax_id.compute_all(
                        (line.price_unit * (1.0 - (line.discount or 0.0) / 100.0)),
                        line.quantity, line.product_id, inv.partner_id)['taxes']
                    for tax in taxes:
                        if inv.type in ('out_invoice', 'in_invoice'):
                            tax_code_id = tax['base_code_id']
                            tax_amount = tax['price_unit'] * line.quantity * tax['base_sign']
                        else:
                            tax_code_id = tax['ref_base_code_id']
                            tax_amount = tax['price_unit'] * line.quantity * tax['ref_base_sign']
        
                        if tax_code_found:
                            if not tax_code_id:
                                continue
                            res.append(dict(mres))
                            res[-1]['price'] = 0.0
                            res[-1]['account_analytic_id'] = False
                        elif not tax_code_id:
                            continue
                        tax_code_found = True
        
                        res[-1]['tax_code_id'] = tax_code_id
                        res[-1]['tax_amount'] = currency.compute(tax_amount, company_currency)
            else:      
                mres = self.move_line_get_item(line)
                mres['invl_id'] = line.id
                res.append(mres)
                tax_code_found = False
                taxes = line.invoice_line_tax_id.compute_all(
                    (line.price_unit * (1.0 - (line.discount or 0.0) / 100.0)),
                    line.quantity, line.product_id, inv.partner_id)['taxes']
                for tax in taxes:
                    if inv.type in ('out_invoice', 'in_invoice'):
                        tax_code_id = tax['base_code_id']
                        tax_amount = tax['price_unit'] * line.quantity * tax['base_sign']
                    else:
                        tax_code_id = tax['ref_base_code_id']
                        tax_amount = tax['price_unit'] * line.quantity * tax['ref_base_sign']
    
                    if tax_code_found:
                        if not tax_code_id:
                            continue
                        res.append(dict(mres))
                        res[-1]['price'] = 0.0
                        res[-1]['account_analytic_id'] = False
                    elif not tax_code_id:
                        continue
                    tax_code_found = True
    
                    res[-1]['tax_code_id'] = tax_code_id
                    res[-1]['tax_amount'] = currency.compute(tax_amount, company_currency)

        return res
    
    @api.model
    def move_line_pack_get_item(self, pack_line):     
        return {
            'type': 'src',
            'name': pack_line.product_id.name,#.split('\n')[0][:64],
            'price_unit': pack_line.price_unit,
            'quantity': pack_line.product_uom_qty,
            'price': pack_line.price_subtotal,
            'account_id': pack_line.account_id.id,
            'product_id': pack_line.product_id.id,
            'uos_id': False,
            'account_analytic_id': False,#line.account_analytic_id.id,
            'taxes': False,#line.invoice_line_tax_id,
        }