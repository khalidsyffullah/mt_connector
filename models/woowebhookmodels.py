# -*- coding: utf-8 -*-
from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)


class SaleOrders(models.Model):
    _inherit = 'sale.order'

    wooc_id = fields.Char(string='WooCommerce ID')

    def process_woocommerce_order(self, order_data, instance_id):
        # Extract billing and shipping details from the JSON data
        billing = order_data.get('billing', {})
        shipping = order_data.get('shipping', {})

        # Create a new sale order with the provided data
        partner_id = self.create_woo_customer(order_data, instance_id)

        # Find the partner invoice ID
        partner_invoice = self.env['res.partner'].sudo().search(
            [('parent_id', '=', partner_id), ('type', '=', 'invoice')], limit=1)

        # If no specific invoice address found, fallback to the main partner ID
        partner_invoice_id = partner_invoice.id if partner_invoice else partner_id

        partner_shipping = self.env['res.partner'].sudo().search(
            [('parent_id', '=', partner_id), ('type', '=', 'delivery')], limit=1)

        partner_shipping_id = partner_shipping.id if partner_shipping else partner_id

        ordername = f"#{order_data.get('id')}"


        self.create({
            'company_id': 1,
            'partner_id': partner_id,
            'partner_invoice_id': partner_invoice_id,
            'partner_shipping_id': partner_shipping_id,
            'payment_term_id': 11,
            'pricelist_id': 1,
            'currency_id': 1,
            'user_id': 2,
            'team_id': 1,
            'create_uid': 2,
            'write_uid': 2,
            'name': ordername,
            'state': 'sale',
            'invoice_status': 'to invoice',
            'validity_date': '2024-09-28',
            'currency_rate': 1.0,
            'amount_untaxed': 199,
            'amount_tax': 199,
            'amount_total': 218,
            'amount_to_invoice':218,
            'locked': False,
            'require_signature': True,
            'require_payment': False,
            'create_date': '2024-08-28',
            'date_order': '2024-08-28',
            'write_date': '2024-08-28',
            'prepayment_percent': 1,
            'warehouse_id': 1,
            'procurement_group_id': 8,
            'picking_policy': 'direct',
            'delivery_status': 'pending',
            'woocomm_instance_id': instance_id,
            'wooc_id': order_data.get('id'),
            'woocomm_order_no': order_data.get('number'),
            'woocomm_payment_method': order_data.get('payment_method'),
            'woocomm_status': order_data.get('status'),
            'woocomm_customer_id': order_data.get('customer_id'),
            'woocomm_order_date': order_data.get('date_created'),
            'woocomm_order_subtotal': order_data.get('subtotal'),
            'woocomm_order_total': order_data.get('total'),
            'is_woocomm_order': True,
            'is_exported': True,

            # Add instance_id if needed for additional logic
        })
        _logger.info(f"Processed WooCommerce order {order_data.get('id')} and created sale order.")

    def create_woo_customer(self, customer, instance_id):
        customer_email = customer.get('billing', {}).get('email')
        customer_woo_id = customer.get('customer_id')
        existing_customer = self.env['res.partner'].sudo().search([('wooc_user_id', '=', customer_woo_id)], limit=1)

        '''
        This is used to update wooc_user_id of a customer, this
        will avoid duplication of customers while syncing customers.
        '''
        customer_without_wooc_user_id = self.env['res.partner'].sudo().search(
            [('wooc_user_id', '=', False), ('email', '=', customer_email), ('type', '=', 'contact')], limit=1)

        # Update existing customer if wooc_user_id is missing
        if not customer_woo_id and existing_customer:
            existing_customer.sudo().write({'wooc_user_id': customer.get('id')})
            return existing_customer.id

        # Create a new customer if no existing one is found
        if not existing_customer and not customer_without_wooc_user_id:
            billing_info = customer.get('billing', {})
            first_name = billing_info.get('first_name')
            last_name = billing_info.get('last_name')
            street = billing_info.get('address_1')
            city = billing_info.get('city')
            complete_name = f"{first_name} {last_name}"

            new_customer_vals = {
                'wooc_user_id': customer.get('id'),
                'email': customer_email,
                'phone': billing_info.get('phone'),
                'name': complete_name,
                'country_id': 19,  # Assuming country_id 19 is for BD (Bangladesh)
                'commercial_partner_id': customer.get('id'),
                'create_uid': 2,  # User ID who creates the record
                'write_uid': 2,  # User ID who writes the record
                'complete_name': complete_name,
                'lang': 'en_US',  # Assuming English as the language
                'tz': 'Asia/Dhaka',  # Timezone
                'type': 'contact',
                'street': street,
                'city': city,
                'write_date': fields.Datetime.now(),
            }

            # Create the new customer record
            new_customer = self.env['res.partner'].sudo().create(new_customer_vals)
            return new_customer.id

        # If customer without wooc_user_id exists, return its ID
        if customer_without_wooc_user_id:
            customer_without_wooc_user_id.sudo().write({'wooc_user_id': customer.get('id')})
            return customer_without_wooc_user_id.id

        # If customer already exists, return its ID
        return existing_customer.id if existing_customer else None
