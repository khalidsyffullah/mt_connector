# -*- coding: utf-8 -*-
import os
import json
from odoo import http, fields
from odoo.http import request
import logging

_logger = logging.getLogger(__name__)


class WebhookController(http.Controller):
    @http.route('/woocommerce/webhook', type='json', auth='public', methods=['POST'], csrf=False)
    def woocommerce_webhook(self):
        global message
        try:
            # Get the raw request data and parse it as JSON
            raw_data = request.httprequest.get_data()
            order_data = json.loads(raw_data)

            # Define the directory where the JSON file will be saved
            save_dir = '/opt/odoo17/custom-addons/mt_odoo_woocommerce_connector/woocommerce_orders'

            # Ensure the directory exists
            if not os.path.exists(save_dir):
                os.makedirs(save_dir)

            # Generate a file name using the order ID or a timestamp
            order_id = order_data.get('id', 'unknown_order')
            file_name = f'order_{order_id}.json'
            file_path = os.path.join(save_dir, file_name)

            # Save the order data as a JSON file
            with open(file_path, 'w') as json_file:
                json.dump(order_data, json_file, indent=4)

            _logger.info(f"Order {order_id} saved successfully at {file_path}.")

            # Check if the order ID exists in the sale_order table's wooc_id column
            SaleOrder = request.env['sale.order'].sudo()
            existing_order = SaleOrder.search([('wooc_id', '=', order_id)], limit=1)

            if existing_order:
                message = f"Order {order_id} exists."
            else:

                # If the order does not exist, check the active woocommerce instances
                WoocommerceInstance = request.env['woocommerce.instance'].sudo()
                active_instances = WoocommerceInstance.search([('active', '=', True)])

                if active_instances:
                    # Get the details of the first active instance
                    first_instance = active_instances[0]
                    instance_id = first_instance.id
                    message = instance_id

                    SaleOrder.process_woocommerce_order(order_data, instance_id)


            return {"status": "success", "message": message}

        except Exception as e:
            _logger.error(f"Failed to save order: {e}")
            return {"status": "error", "message": f"Failed to save order: {e}"}
