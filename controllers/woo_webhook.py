# controllers/main_controller.py

from odoo import http
from odoo.http import request
import json
import os
import logging

_logger = logging.getLogger(__name__)

class WebhookController(http.Controller):
    @http.route('/woocommerce/webhook', type='json', auth='public', methods=['POST'], csrf=False)
    def woocommerce_webhook(self):
        try:
            raw_data = request.httprequest.get_data()
            order_data = json.loads(raw_data)

            order_id = order_data.get('id')
            if not order_id:
                _logger.error("Order ID is missing from the request.")
                return {"status": "error", "message": "Order ID is missing from the request."}

            sale_order_exists = request.env['sale.order'].sudo().search([('wooc_id', '=', order_id)], limit=1)

            if sale_order_exists:
                _logger.info(f"Order {order_id} already exists in the sale.order table.")
                return {"status": "warning", "message": f"Order {order_id} already exists."}

            save_dir = '/opt/odoo17/custom-addons/mt_odoo_woocommerce_connector/woocommerce_orders'

            if not os.path.exists(save_dir):
                os.makedirs(save_dir)

            file_name = f'order_{order_id}.json'
            file_path = os.path.join(save_dir, file_name)

            with open(file_path, 'w') as json_file:
                json.dump(order_data, json_file, indent=4)

            _logger.info(f"Order {order_id} saved successfully at {file_path}.")

            # Call the create_sale_order method
            SaleOrder = request.env['sale.order']
            sale_order_instance = SaleOrder.with_context({'woocomm_instance_id': 1})
            sale_order_instance.create_sale_order(order_data, 1)

            return {"status": "success", "message": f"Order {order_id} created successfully."}

        except Exception as e:
            _logger.error(f"Failed to save order: {e}")

            failed_dir = '/opt/odoo17/custom-addons/mt_odoo_woocommerce_connector/woocommerce_orders/failed'
            if not os.path.exists(failed_dir):
                os.makedirs(failed_dir)

            failed_file_path = os.path.join(failed_dir, f'failed_order_{order_id}.txt')
            with open(failed_file_path, 'w') as failed_file:
                failed_file.write(str(order_id))

            return {"status": "error", "message": f"Failed to process order: {e}"}
