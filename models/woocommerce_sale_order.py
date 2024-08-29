# -*- coding: utf-8 -*-

import time
import logging

from woocommerce import API
from odoo.exceptions import UserError
from odoo import api, fields, _, models
from datetime import datetime
from odoo.tools import config

_logger = logging.getLogger(__name__)

class SaleOrder(models.Model):
    _inherit = 'sale.order'
    
    @api.model
    def default_get(self, fields):
        res = super(SaleOrder, self).default_get(fields)
        if self.env['woocommerce.instance']._context.get('woocomm_instance_id'):
            res['woocomm_instance_id'] = self.env['woocommerce.instance']._context.get('woocomm_instance_id')
            
        return res

    wooc_id = fields.Char('WooCommerce ID')
    woocomm_order_no = fields.Char('WooCommerce Order No.')
    woocomm_payment_method = fields.Char("WooCommerce Payment Method")
    woocomm_status = fields.Selection([
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('on-hold', 'On Hold'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
        ('refunded', 'Refunded'),
        ('failed', 'Failed'),
        ('trash', 'Trash')], string="WooCommerce Order Status")    
    woocomm_order_date = fields.Date(string="WooCommerce Order Date")
    woocomm_order_subtotal = fields.Float('WooCommerce Order Subtotal')
    woocomm_order_total_tax = fields.Float('WooCommerce Order Total Tax')
    woocomm_order_total = fields.Float('WooCommerce Order Total Price')
    woocomm_order_note = fields.Char('WooCommerce Order Note from Customer')
    woocomm_customer_id = fields.Char('WooCommerce Customer Id.')
    
    is_exported = fields.Boolean('Synced In WooCommerce', default=False)
    is_woocomm_order = fields.Boolean('Is WooCommerce Order', default=False)
    
    woocomm_instance_id = fields.Many2one('woocommerce.instance', ondelete='cascade')


    @api.model_create_multi
    def create(self, vals_list):
        
        for vals in vals_list:
            _logger.info('\n\n\n\n  create_sale_order  self =  %s \n\n\n\n' % (vals['pricelist_id']) )
            if vals['pricelist_id']:
                pricelist_id = self.env['product.pricelist'].sudo().search([('id', '=', vals['pricelist_id'])], limit=1)
                woocomm_instance_id = self.env['woocommerce.instance'].sudo().search([('id', '=', vals['woocomm_instance_id'])], limit=1)
                if pricelist_id.currency_id.name != woocomm_instance_id.wooc_currency:
                    raise UserError(_("The Pricelist currency and WooCommerce currency does not match. \n\nPlease update the pricelist currency or authenticate WooCommerce instance again!!!"))
            
        return super(SaleOrder,self).create(vals_list)
        
    @api.onchange("invoice_count")
    def update_invoice_instance_id(self):
        for id in self.invoice_ids:
            id.woocomm_instance_id = self.woocomm_instance_id
            
    @api.depends('invoice_count')
    def _set_invoice_instance_id(self):
        for order in self:
            invoices = order.order_line.invoice_lines.move_id.filtered(lambda r: r.move_type in ('out_invoice', 'out_refund'))
        for invoice in invoices:
            invoice.woocomm_instance_id = self.woocomm_instance_id


    def init_wc_api(self, wooc_instance):
        if wooc_instance.is_authenticated:
            try:
                woo_api = API(
                            url=wooc_instance.shop_url,
                            consumer_key=wooc_instance.wooc_consumer_key,
                            consumer_secret=wooc_instance.wooc_consumer_secret,
                            wp_api=True,
                            version=wooc_instance.wooc_api_version
                        )
                req_data = woo_api.get("")
                
                return woo_api
            except Exception as error:
                raise UserError(_("Please check your connection and try again"))
        else :
            raise UserError(_("Connection Instance needs to authenticate first. \n Please try after authenticating connection!!!"))
        
    def get_all_orders(self, wooc_instance, limit=100):
        woo_api = self.init_wc_api(wooc_instance)
                
        url = "orders"
        get_next_page = True
        page = 1
        while get_next_page:
            try:
                # _logger.info('\n\n\n\n  page  =  %s \n\n\n\n' % (page) )
                orders = woo_api.get(url, params={'orderby': 'id', 'order': 'asc','per_page': limit, 'page': page})
                page += 1

            except Exception as error:
                _logger.info('\n\n\n\n  Error Order on page=  %s \n\n\n\n' % (page) )
                time.sleep(2)
                continue

            if orders.status_code == 200:
                if orders.content:
                    parsed_orders = orders.json()
                    for order in parsed_orders:
                        yield order
                        
                    if len(parsed_orders) < limit:
                        get_next_page = False 
                else:
                    get_next_page = False 
            else:
                    get_next_page = False 
                    
    def cron_import_woocomm_orders(self):
        all_instances = self.env['woocommerce.instance'].sudo().search([])
        for rec in all_instances:
            if rec:
                self.env['sale.order'].import_sale_order(rec)
                  
    def import_sale_order(self, instance_id, is_force_update = False):
        
        for order in self.get_all_orders(instance_id):
            
            if not is_force_update:
                exist = self.sudo().search([('wooc_id', '=', order['id'])],limit=1)
                
                if exist:
                    continue
            
            _logger.info('\n\n\n\n  Importing Sale Order Data - #%s \n\n\n\n' % (order['number']) )            
            self.create_sale_order(order, instance_id)
        return

    def create_sale_order(self, order, instance_id):

        res_partner = self.env['res.partner'].sudo().search(
                    [('wooc_user_id', '=', order['customer_id'])], limit=1)
        
        if not res_partner:
            customer_data  = self.env['res.partner'].get_wooc_customer(order['customer_id'], instance_id)
            self.env['res.partner'].create_customer(customer_data, instance_id)
            
            res_partner = self.env['res.partner'].sudo().search(
                    [('wooc_user_id', '=', order['customer_id'])], limit=1)
        
        if res_partner:
            
            dict_so = {}
            dict_so['wooc_id'] = order['id']
            dict_so['partner_id'] = res_partner.id                
            dict_so['name'] = "#" + order['number']
            dict_so['woocomm_instance_id'] = instance_id.id
            dict_so['woocomm_order_no'] = order['number']
            dict_so['woocomm_customer_id'] = order['customer_id']
            dict_so['company_id'] = instance_id.wooc_company_id.id
            dict_so['state'] = 'sale'
            dict_so['woocomm_order_subtotal'] = float(order['total'])
            dict_so['woocomm_order_total_tax'] = float(order['total_tax'])
            dict_so['woocomm_order_total'] = float(order['total'])
            dict_so['woocomm_order_date'] = order['date_created']
            dict_so['amount_total'] = float(order['total'])
            dict_so['woocomm_payment_method'] = order['payment_method']
            dict_so['woocomm_status'] = order['status']
            dict_so['woocomm_order_note'] = order['customer_note']
            dict_so['is_exported'] = True                

            _logger.info('\n\n\n\n  create_sale_order  dict_so =  %s \n\n\n\n' % (dict_so) )



            sale_order = self.env['sale.order'].sudo().search([('wooc_id', '=', order['id'])], limit=1)
            if not sale_order:
                
                dict_so['payment_term_id'] = self.create_payment_terms(order) 
                dict_so['is_woocomm_order'] = True
                
                so_obj = self.env['sale.order'].sudo().create(dict_so)

                create_invoice = self.create_woocomm_sale_order_lines(so_obj.id, instance_id, order)
                
                self.create_woocomm_shipping_lines(so_obj.id, instance_id, order)
                                    
                if order["date_paid"]:
                    # so_obj.action_confirm()

                    if create_invoice == True:
                        so_obj._create_invoices()
                        
                # To cancel the cancelled orders from woocommerce
                if order['status'] == "cancelled":
                    soc = self.env['sale.order.cancel'].sudo().create({'order_id' : so_obj.id})
                    soc.action_cancel()
                    
                self.env.cr.commit()  
            else:
                if sale_order.state != 'done':       
                                  
                    sale_order.sudo().write(dict_so)
                                       
                    for sol_item in order['line_items']:
                        res_product = self.env['product.product'].sudo().search(
                            ['|', ('woocomm_variant_id', '=', sol_item.get('product_id')), ('woocomm_variant_id', '=', sol_item.get('variation_id'))],
                            limit=1)

                        if res_product:
                            s_order_line = self.env['sale.order.line'].sudo().search(
                                [('product_id', '=', res_product.id),
                                    (('order_id', '=', sale_order.id))], limit=1)

                            if s_order_line:
                                tax_id_list= self.add_tax_lines( instance_id, sol_item.get('taxes'))
                        
                                so_line = self.env['sale.order.line'].sudo().search(
                                    ['&', ('product_id', '=', res_product.id),
                                        (('order_id', '=', sale_order.id))], limit=1)
                                if so_line:
                                    so_line_data = {
                                        'name': res_product.name,                                        
                                        'product_id': res_product.id,
                                        'woocomm_so_line_id': sol_item.get('id'),
                                        'tax_id': [(6, 0, tax_id_list)],
                                        'product_uom_qty': sol_item.get('quantity'),                                        
                                        'price_unit': float(sol_item.get('price')) if sol_item.get('price') != '0.00' else 0.00,                                        
                                    }

                                    sol_update = so_line.write(so_line_data)
                            else:
                                so_line = self.create_sale_order_line(sale_order.id, instance_id, sol_item)
                                
                        self.env.cr.commit()
                        
                    if order['shipping_lines']:

                        for sh_line in order['shipping_lines']:
                            shipping = self.env['delivery.carrier'].sudo().search(['&', ('woocomm_method_id', '=', sh_line['method_id']), ('woocomm_instance_id', '=', instance_id.id)], limit=1)    
                            
                            so_line = self.env['sale.order.line'].sudo().search(['&', ('is_delivery', '=', True),(('order_id', '=', sale_order.id))], limit=1)
                            if shipping and shipping.product_id:
                                
                                tax_id_list = self.add_tax_lines(instance_id, sh_line.get('taxes'))
                                shipping_vals = {
                                    'product_id': shipping.product_id.id,
                                    'name':shipping.product_id.name,
                                    'price_unit': float(sh_line['total']),
                                    'is_delivery' : True,
                                    'tax_id': [(6, 0, tax_id_list)]
                                }
                                if shipping.product_id.id == so_line.product_id.id:
                                    _logger.info('\n\n\n\n so_shipping_line_data -- %s  \n\n\n\n\n' % (shipping_vals))
                                    shipping_update = so_line.write(shipping_vals)
                                else:
                                    shipping_vals.update({"woocomm_so_line_id":sh_line['id'],'order_id': sale_order.id,})
                                    so_line.unlink()
                                    self.env['sale.order.line'].sudo().create(shipping_vals)

                                self.env.cr.commit()

                    else:
                        #To remove shipping price, if the shipping not selected in the woocommerce site due shipping conditions.
                        so_line = self.env['sale.order.line'].sudo().search(['&', ('is_delivery', '=', True),(('order_id', '=', sale_order.id))], limit=1)
                        
                        if so_line:
                            so_line.unlink()

                    # To cancel the cancelled orders from woocommerce
                    if order['status'] == "cancelled":
                        soc = self.env['sale.order.cancel'].sudo().create({'order_id' : sale_order.id})
                        soc.action_cancel()                         
                        
        return
      
    def create_woocomm_sale_order_lines(self, so_id, instance_id, order):

        create_invoice = False
        for sol_item in order.get('line_items'):
            
            so_line = self.create_sale_order_line(so_id, instance_id, sol_item)
            if so_line:
                if so_line.qty_to_invoice > 0:
                    create_invoice = True
            
        return create_invoice
   
    def create_sale_order_line(self, so_id, instance_id, line_item):
        
        res_product = ''     
        if line_item.get('product_id') or line_item.get('variation_id'):
            res_product = self.env['product.product'].sudo().search(
                ['|', ('woocomm_variant_id', '=', line_item.get('product_id')), ('woocomm_variant_id', '=', line_item.get('variation_id'))],
                limit=1)
            
            if not res_product:
                _logger.info('\n\n\n\n  Product not exist to create Order  =  %s \n\n\n\n' % (line_item) )
                
                self.env['product.template'].sudo().get_wooc_product_data(line_item.get('product_id'), instance_id)
                res_product = self.env['product.product'].sudo().search(
                ['|', ('woocomm_variant_id', '=', line_item.get('product_id')), ('woocomm_variant_id', '=', line_item.get('variation_id'))],
                limit=1)
                
                # need to check about creating product using existing function
                
            if res_product:
                dict_l = {}
                dict_l['woocomm_so_line_id'] = line_item.get('id')
                dict_l['order_id'] = so_id
                dict_l['product_id'] = res_product.id
                dict_l['name'] = res_product.name
                dict_l['product_uom_qty'] = line_item.get('quantity')
                dict_l['price_unit'] = float(line_item.get('price')) if line_item.get('price') != '0.00' else 0.00
                
                if line_item.get('taxes'):
                    _logger.info('\n\n\n\n  Taxes  =  %s \n\n\n\n' % (line_item.get('taxes')) )
                    tax_id_list= self.add_tax_lines(instance_id, line_item.get('taxes'))
                    dict_l['tax_id'] = [(6, 0, tax_id_list)]
                                   
                if line_item.get('currency'):
                    cur_id = self.env['res.currency'].sudo().search([('name', '=', line_item.get('currency'))], limit=1)
                    dict_l['currency_id'] = cur_id.id
                    
                return self.env['sale.order.line'].sudo().create(dict_l)
            
            return False
  
    def create_payment_terms(self, order):

        if order['payment_method_title']:
            pay_id = self.env['account.payment.term']
            payment = pay_id.sudo().search([('name', '=', order['payment_method_title'])], limit=1)
            if not payment:
                create_payment = payment.sudo().create({'name': order['payment_method_title']})
                if create_payment:
                    return create_payment.id
            else:
                return payment.id
        return False  

    def create_woocomm_shipping_lines(self, so_id, instance_id, order):
        for sh_line in order['shipping_lines']:
            shipping = self.env['delivery.carrier'].sudo().search(['&', ('woocomm_method_id', '=', sh_line['method_id']), ('woocomm_instance_id', '=', instance_id.id)], limit=1)
            if not shipping:
                delivery_product = self.env['product.product'].sudo().create({
                    'name': sh_line['method_title'],
                    'detailed_type': 'service',
                    'taxes_id': [(6, 0, [])]
                })
                               
                vals = {
                    'wooc_id': sh_line['id'],
                    'name': sh_line['method_title'],
                    'product_id': delivery_product.id,
                    'fixed_price': float(sh_line['total']),
                    'woocomm_method_id' : sh_line['method_id'],
                    'is_woocomm': True,
                    'woocomm_instance_id': instance_id.id,                    
                }
                shipping = self.env['delivery.carrier'].sudo().create(vals)
                

            tax_id_list = self.add_tax_lines(instance_id, sh_line.get('taxes'))
            _logger.info('\n\n\n\n  shipping tax %s  \n\n\n\n' % (tax_id_list) )
                       
            if shipping and shipping.product_id:
                shipping_vals = {
                    "woocomm_so_line_id":sh_line['id'],
                    'product_id': shipping.product_id.id,
                    'name':shipping.product_id.name,
                    'price_unit': float(sh_line['total']),
                    'order_id': so_id,
                    'is_delivery' : True,
                    'tax_id': [(6, 0, tax_id_list)]
                }
                shipping_so_line = self.env['sale.order.line'].sudo().create(shipping_vals)
                
        self.env.cr.commit()
        
    def add_tax_lines(self, instance_id, tax_lines):
        
        tax_id_list = []
        if tax_lines:
            for tax_line in tax_lines:
               
                tax_data = self.env['account.tax'].sudo().get_wooc_tax(tax_line['id'], instance_id)
                
                if tax_data:
                    acc_tax = self.env['account.tax'].sudo().create_tax(tax_data, instance_id)
                    tax_id_list.append(acc_tax.id)                  
            
        return tax_id_list   
  
    def woocomm_order_update_button(self):
        
        woo_api = self.init_wc_api(self.woocomm_instance_id)
        
        data =  { 
                 "customer_note": self.woocomm_order_note,
                 "status": self.woocomm_status,
                 }
        
        r_data = woo_api.put("orders/%s"%self.wooc_id, data)   
        
        if r_data.status_code == 200:
            return self.env['message.wizard'].success("Data Updated")
        else:
            return self.env['message.wizard'].fail("Data Update Failed")
                    
    def get_current_order(self):
        selected_ids = self.env.context.get('active_ids', [])
        order_id = self.sudo().search([('id', 'in', selected_ids)])

        if not order_id:
            raise UserError(_("Please select Order!!!"))
        else:
            return order_id
 
    def is_cancelled(self):
        if self.state == "cancel":
            raise UserError(_("This action cann't perform in a cancelled order."))       

    def action_woocomm_order_wizard(self):
        
        self.is_cancelled()
        
        action = self.env.ref("mt_odoo_woocommerce_connector.action_woocomm_order_actions_wizard").read()[0]
        action.update({
            'context': "{'woocomm_instance_id': " + str(self.woocomm_instance_id.id) + "}",
        })        
        return action
    
    
    # WooCommerce Refund Code
    def order_refund_create(self, instance_id):
        
        order_ids = self.get_current_order()
        
        for order in order_ids: 
            self.woocomm_full_refund(instance_id, order)
            
    def woocomm_full_refund(self, instance_id, order):
        woo_api = self.init_wc_api(instance_id)
        
        data = {}       
        data.update( {'reason' : "Full refund from odoo", "api_refund" : False})
        
        data['line_items'] = []
        so_lines = self.env['sale.order.line'].sudo().search([('order_id', '=', order.id)])
        for line in so_lines:
            if line.woocomm_so_line_id and int(line.product_uom_qty) > 0 and not line.is_delivery:
                line_items = {
                    "id": line.woocomm_so_line_id,
                    "quantity": int(line.product_uom_qty),
                    "refund_total": line.price_subtotal,
                    "refund_tax": []
                }
                line_items['refund_tax'].append({"id": "1", "refund_total": line.price_tax })
                data['line_items'].append(line_items)
                
            if line.woocomm_so_line_id and int(line.product_uom_qty) > 0 and line.is_delivery:
                
                tax_items = {"id": line.woocomm_so_line_id, "refund_total": line.price_subtotal, 'refund_tax' : []}
                tax_items['refund_tax'].append({"id": "1", "refund_total": line.price_tax })
                data['line_items'].append(tax_items)  
                                           
            
        try:   
            wc_refund = woo_api.post("orders/%s/refunds"%order.wooc_id, data)
            
            _logger.info('\n\n\n\n Result Refund Array   =  %s \n\n\n\n' % (wc_refund.json()) )  
            
            if wc_refund.status_code == 201:
                if wc_refund.content:
                    refund = wc_refund.json()
            
        except Exception as error:
            _logger.info('\n\n\n\n  Error   =  %s \n\n\n\n' % (error.response.__dict__) )
            raise UserError(_(error.response.body))
  
    def woocomm_order_cancel(self, instance_id):

        woo_api = self.init_wc_api(instance_id)
        
        order_id = self.get_current_order()
        data =  { "status": 'cancelled',}
        
        cancel_order = woo_api.put("orders/%s"%order_id.wooc_id, data)   
        if cancel_order.status_code == 200:
            cancel_order = cancel_order.json()
            soc = self.env['sale.order.cancel'].sudo().create({'order_id' : order_id.id})
            soc.action_cancel()
            
            order_id.woocomm_status = cancel_order['status']
            
            return self.env['message.wizard'].success("Order Cancelled!!!")
        else:
            return self.env['message.wizard'].fail("Failed to Cancel the order.")   

    def woocomm_force_info_update(self, instance_id):
        woo_api = self.init_wc_api(instance_id)
               
        order_id = self.get_current_order()
        
        try:
            order = woo_api.get("orders/%s"%order_id.wooc_id,)
            
            if order.status_code == 200:
                self.create_sale_order(order.json(), instance_id)
        
        except Exception as error:
            raise UserError(_(error))          
              
# Create new orders
    def woocomm_new_orders(self, instance_id):
               
        order_ids = self.get_current_order()
        
        for order in order_ids: 
            self.create_woocomm_new_order(instance_id, order)
     
    def create_woocomm_new_order(self, instance_id, order):
        woo_api = self.init_wc_api(instance_id)
        
        data = {}       
        data.update({   "customer_id": order.partner_id.wooc_user_id,
                        'line_items' : [],
                        'shipping_lines' : []})
        
        data_cus = self.get_order_address(order.partner_id)
        data.update(data_cus)
        _logger.info('\n\n\n\n  new sale order customer data =  %s \n\n\n\n' % (data_cus) )
        
        so_lines = self.env['sale.order.line'].sudo().search([('order_id', '=', order.id)])
        for line in so_lines:
            if line.product_id.woocomm_variant_id and int(line.product_uom_qty) > 0:
                line_items = {
                    "product_id": line.product_id.product_tmpl_id.wooc_id,
                    "quantity": int(line.product_uom_qty),
                }
                if line.product_id.woocomm_variant_id :
                    line_items.update({"variation_id": line.product_id.woocomm_variant_id,})
                
                data['line_items'].append(line_items)
                
            if line.is_delivery:
                shipping_line = self.env['delivery.carrier'].sudo().search([('product_id', '=', line.product_id.id)], limit=1)
                
                data_shipping_line = {}

                data_shipping_line.update({"method_id": shipping_line.woocomm_method_id,
                                           "method_title": shipping_line.name,
                                           })

                    
                if float(line.price_unit) != float(shipping_line.fixed_price):
                    data_shipping_line.update({"total": str(line.price_unit)})
                else:
                    data_shipping_line.update({"total": str(shipping_line.fixed_price)})
                    
                data['shipping_lines'].append(data_shipping_line)
                
        _logger.info('\n\n\n\n  new sale order data =  %s \n\n\n\n' % (data) )
        
        new_order = woo_api.post("orders", data)

        if new_order.status_code == 400:            
            if(new_order.json()['code'] == 'woocommerce_rest_invalid_shipping_item'):
                #import all shipping methods from WooCommerce
                self.env['delivery.carrier'].import_shipping_method(instance_id)
                
                raise UserError(_("Shippping Method Not Exist!!!, \nChoose correct method from list, thats under the current store instance!!!"))

        
        if new_order.status_code == 201:
            new_order = new_order.json()   
            order.update({'wooc_id' : new_order['id'], 'is_exported':True, 'name' : "#" + new_order['number'] })
            
            # To create Order data in db after exporting.
            self.create_sale_order(new_order, instance_id)
            
            order.update({'is_woocomm_order' : False })
                      
    def get_order_address(self, customer):
        
            contacts_billing = self.env['res.partner'].sudo().search([('parent_id', '=', customer.id), ('type', '=', 'invoice')],limit=1)
            contacts_delivery = self.env['res.partner'].sudo().search([('parent_id', '=', customer.id), ('type', '=', 'delivery')],limit=1)
            
            if customer:
                email = getattr(customer, 'email') or ''
            
            if contacts_billing:
                billing_addr = self.env['res.partner'].sudo().set_address(contacts_billing)
            else:     
                billing_addr = self.env['res.partner'].sudo().set_address(customer)  
                        
            if contacts_delivery:
                delivery_addr = self.env['res.partner'].sudo().set_address(contacts_delivery)
            else:     
                delivery_addr = billing_addr          
            
            billing_addr.update({'email' : email})            
            
            return {"billing" : billing_addr , "shipping" : delivery_addr }

# set paid manually in woocommerce
    def woocomm_set_paid(self, instance_id):
        woo_api = self.init_wc_api(instance_id)

        order_ids = self.get_current_order()
        
        for order in order_ids: 
            data =  { 
                    "set_paid": True,
                    }
            
            r_data = woo_api.put("orders/%s"%order.wooc_id, data)   
            
        if r_data.status_code == 200:
            
            self.create_sale_order(r_data.json(), instance_id)
            
            return self.env['message.wizard'].success("Data Updated")
        else:
            return self.env['message.wizard'].fail("Data Update Failed")            

    def action_generate_invoice(self):
        
        self.is_cancelled()
        
        action = self.env.ref("mt_odoo_woocommerce_connector.action_woocomm_wizard_generate_invoice").read()[0]
        action.update({
            'context': "{'woocomm_instance_id': " + str(self.woocomm_instance_id.id) + "}",
        })         
        return action

    def order_generate_invoice(self, instance_id):
               
        order_ids = self.get_current_order()
        
        for order in order_ids:
            for order_invoice in  order.invoice_ids:
                if order_invoice.state == "draft":
                    order_invoice.action_post() #to confirm invoice 

                if order_invoice.state == "posted" and order_invoice.payment_state == "not_paid":
                    order_invoice.action_register_payment() #to register payment 

           

        
                
class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    woocomm_so_line_id = fields.Char('WooCommerce Line ID')
    
    woocomm_vendor = fields.Many2one('res.partner', 'WooCommerce Vendor')
