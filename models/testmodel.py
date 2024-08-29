# -*- coding: utf-8 -*-
from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    wooc_id = fields.Char(string='WooCommerce ID')

    def process_woocommerce_order(self, order, instance_id):
        # Step 1: Find or Create the Customer (res.partner)
        res_partner = self.env['res.partner'].sudo().search(
            [('wooc_user_id', '=', order['customer_id'])], limit=1)

        if not res_partner:
            customer_data = self.env['res.partner'].get_wooc_customer(order['customer_id'], instance_id)
            self.env['res.partner'].create_customer(customer_data, instance_id)
            res_partner = self.env['res.partner'].sudo().search(
                [('wooc_user_id', '=', order['customer_id'])], limit=1)

        # Step 2: If Customer Exists, Create or Update the Sale Order
        if res_partner:
            dict_so = {
                'wooc_id': order['id'],
                'partner_id': res_partner.id,
                'name': "#" + order['number'],
                'woocomm_instance_id': instance_id.id,
                'woocomm_order_no': order['number'],
                'woocomm_customer_id': order['customer_id'],
                'company_id': instance_id.wooc_company_id.id,
                'state': 'sale',
                'woocomm_order_subtotal': float(order['total']),
                'woocomm_order_total_tax': float(order['total_tax']),
                'woocomm_order_total': float(order['total']),
                'woocomm_order_date': order['date_created'],
                'amount_total': float(order['total']),
                'woocomm_payment_method': order['payment_method'],
                'woocomm_status': order['status'],
                'woocomm_order_note': order['customer_note'],
                'is_exported': True,
            }

            # Step 3: Log the Sale Order Data
            _logger.info('\n\n\n\n  process_woocommerce_order dict_so =  %s \n\n\n\n' % dict_so)

            # Step 4: Check for Existing Sale Order
            sale_order = self.env['sale.order'].sudo().search([('wooc_id', '=', order['id'])], limit=1)
            if not sale_order:
                dict_so['payment_term_id'] = self.create_payment_terms(order)
                dict_so['is_woocomm_order'] = True

                so_obj = self.env['sale.order'].sudo().create(dict_so)

                # Step 5: Create Sale Order Lines
                create_invoice = self.create_woocomm_sale_order_lines(so_obj.id, instance_id, order)

                # Step 6: Create Shipping Lines
                self.create_woocomm_shipping_lines(so_obj.id, instance_id, order)

                # Step 7: Handle Paid Orders and Create Invoices
                if order["date_paid"]:
                    if create_invoice:
                        so_obj._create_invoices()

                # Step 8: Handle Canceled Orders
                if order['status'] == "cancelled":
                    soc = self.env['sale.order.cancel'].sudo().create({'order_id': so_obj.id})
                    soc.action_cancel()

                # Commit Transaction
                self.env.cr.commit()

            else:
                if sale_order.state != 'done':
                    sale_order.sudo().write(dict_so)

                    # Step 9: Update Sale Order Lines
                    for sol_item in order['line_items']:
                        res_product = self.env['product.product'].sudo().search(
                            ['|', ('woocomm_variant_id', '=', sol_item.get('product_id')),
                             ('woocomm_variant_id', '=', sol_item.get('variation_id'))],
                            limit=1)

                        if res_product:
                            s_order_line = self.env['sale.order.line'].sudo().search(
                                [('product_id', '=', res_product.id),
                                 ('order_id', '=', sale_order.id)], limit=1)

                            if s_order_line:
                                tax_id_list = self.add_tax_lines(instance_id, sol_item.get('taxes'))

                                so_line_data = {
                                    'name': res_product.name,
                                    'product_id': res_product.id,
                                    'woocomm_so_line_id': sol_item.get('id'),
                                    'tax_id': [(6, 0, tax_id_list)],
                                    'product_uom_qty': sol_item.get('quantity'),
                                    'price_unit': float(sol_item.get('price')) if sol_item.get(
                                        'price') != '0.00' else 0.00,
                                }
                                s_order_line.write(so_line_data)
                            else:
                                self.create_sale_order_line(sale_order.id, instance_id, sol_item)

                            self.env.cr.commit()

                    # Step 10: Update or Remove Shipping Lines
                    if order['shipping_lines']:
                        for sh_line in order['shipping_lines']:
                            shipping = self.env['delivery.carrier'].sudo().search(
                                ['&', ('woocomm_method_id', '=', sh_line['method_id']),
                                 ('woocomm_instance_id', '=', instance_id.id)], limit=1)

                            so_line = self.env['sale.order.line'].sudo().search(
                                ['&', ('is_delivery', '=', True), ('order_id', '=', sale_order.id)], limit=1)
                            if shipping and shipping.product_id:
                                tax_id_list = self.add_tax_lines(instance_id, sh_line.get('taxes'))
                                shipping_vals = {
                                    'product_id': shipping.product_id.id,
                                    'name': shipping.product_id.name,
                                    'price_unit': float(sh_line['total']),
                                    'is_delivery': True,
                                    'tax_id': [(6, 0, tax_id_list)]
                                }
                                if shipping.product_id.id == so_line.product_id.id:
                                    _logger.info('\n\n\n\n so_shipping_line_data -- %s  \n\n\n\n\n' % (shipping_vals))
                                    so_line.write(shipping_vals)
                                else:
                                    shipping_vals.update(
                                        {"woocomm_so_line_id": sh_line['id'], 'order_id': sale_order.id, })
                                    so_line.unlink()
                                    self.env['sale.order.line'].sudo().create(shipping_vals)

                                self.env.cr.commit()
                    else:
                        so_line = self.env['sale.order.line'].sudo().search(
                            ['&', ('is_delivery', '=', True), ('order_id', '=', sale_order.id)], limit=1)
                        if so_line:
                            so_line.unlink()

                    # Handle Canceled Orders
                    if order['status'] == "cancelled":
                        soc = self.env['sale.order.cancel'].sudo().create({'order_id': sale_order.id})
                        soc.action_cancel()

        return

    def get_customer_id(self, order_data):
        """Helper method to find or create the customer based on WooCommerce data."""
        customer_data = order_data.get('billing', {})
        partner = self.env['res.partner'].search([('email', '=', customer_data.get('email'))], limit=1)
        if not partner:
            partner = self.env['res.partner'].create({
                'name': customer_data.get('first_name') + ' ' + customer_data.get('last_name'),
                'email': customer_data.get('email'),
                'phone': customer_data.get('phone'),
                'street': customer_data.get('address_1'),
                'city': customer_data.get('city'),
                'zip': customer_data.get('postcode'),
                'country_id': self.env['res.country'].search([('code', '=', customer_data.get('country'))], limit=1).id,
            })
        return partner.id

    def get_order_lines(self, order_data):
        """Helper method to generate order lines from WooCommerce data."""
        order_lines = []
        for item in order_data.get('line_items', []):
            product = self.env['product.template'].search([('wooc_id', '=', item['product_id'])], limit=1)
            if product:
                order_lines.append((0, 0, {
                    'product_id': product.product_variant_id.id,
                    'product_uom_qty': item.get('quantity'),
                    'price_unit': item.get('price'),
                }))
        return order_lines


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    wooc_id = fields.Char(string='WooCommerce ID')
