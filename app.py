from flask import Flask, jsonify, request
from flask_cors import CORS
import xmlrpc.client
import datetime

app = Flask(__name__)
CORS(app)

ODOO_URL = "https://sys.2segypt.com"
DB = "sys.2segypt.com"
USERNAME = "O.abdelhakam@2segypt.com"
API_KEY = "bbdb587bab5f857b5641092a2c7f9ac002266d5f"

# تخزين المهام محلياً (مؤقتاً داخل الذاكرة أو ملف JSON)
tasks_store = []

def get_odoo_connection():
    common = xmlrpc.client.ServerProxy(f'{ODOO_URL}/xmlrpc/2/common')
    uid = common.authenticate(DB, USERNAME, API_KEY, {})
    models = xmlrpc.client.ServerProxy(f'{ODOO_URL}/xmlrpc/2/object')
    return uid, models

@app.route('/api/sync-sales', methods=['POST'])
def sync_sales():
    """سحب أحدث المبيعات من نقاط البيع (POS) وتحديد النواقص"""
    try:
        uid, models = get_odoo_connection()
        if not uid:
            return jsonify({"status": "error", "message": "فشل الاتصال بـ Odoo"}), 401
        
        # استرجاع خطوط طلبات نقاط البيع لليوم الحالي
        today = datetime.date.today().isoformat()
        pos_lines = models.execute_kw(DB, uid, API_KEY, 'pos.order.line', 'search_read', [
            [['create_date', '>=', f'{today} 00:00:00']]
        ], {'fields': ['product_id', 'qty'], 'limit': 100})
        
        # معالجة الأصناف وتصنيفها
        # تصنيف افتراضي للأقسام: يمكن ربطه بـ pos_categ_id أو اسم الفئة في Odoo
        new_tasks = []
        for line in pos_lines:
            product_id = line['product_id'][0]
            product_name = line['product_id'][1]
            qty_sold = line['qty']
            
            # فحص رصيد الستوك المتاح
            stock_info = models.execute_kw(DB, uid, API_KEY, 'product.product', 'search_read', [
                [['id', '=', product_id]]
            ], {'fields': ['barcode', 'qty_available', 'categ_id']})
            
            if stock_info:
                stock_item = stock_info[0]
                categ_name = stock_item.get('categ_id', [0, ''])[1].lower()
                
                # تحديد القسم بناءً على تصنيف أودو
                section = "Women"
                if "kid" in categ_name:
                    section = "Kids"
                elif "men" in categ_name or "man" in categ_name:
                    section = "Men"
                elif "acc" in categ_name:
                    section = "Accessories"
                
                # إضافة المهمة لو كان هناك رصيد متبقي في الستوك
                if stock_item['qty_available'] > 0:
                    new_tasks.append({
                        "id": f"{product_id}_{len(new_tasks)}",
                        "product_name": product_name,
                        "barcode": stock_item.get('barcode', '-'),
                        "qty_needed": int(qty_sold),
                        "stock_available": int(stock_item['qty_available']),
                        "section": section,
                        "status": "pending",  # pending, done, skipped
                        "timestamp": datetime.datetime.now().strftime("%H:%M")
                    })
        
        global tasks_store
        tasks_store = new_tasks
        return jsonify({"status": "success", "count": len(new_tasks), "tasks": tasks_store})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/tasks', methods=['GET'])
def get_tasks():
    section = request.args.get('section')
    if section and section != "Admin":
        filtered = [t for t in tasks_store if t['section'].lower() == section.lower()]
        return jsonify(filtered)
    return jsonify(tasks_store)

@app.route('/api/tasks/<task_id>', methods=['POST'])
def update_task_status(task_id):
    data = request.json
    status = data.get('status')
    for task in tasks_store:
        if task['id'] == task_id:
            task['status'] = status
            task['completed_at'] = datetime.datetime.now().strftime("%H:%M:%S")
            return jsonify({"status": "success", "task": task})
    return jsonify({"status": "error", "message": "Task not found"}), 404

@app.route('/api/report', methods=['GET'])
def get_daily_report():
    sections = ["Kids", "Women", "Men", "Accessories"]
    report = {}
    for sec in sections:
        sec_tasks = [t for t in tasks_store if t['section'].lower() == sec.lower()]
        report[sec] = {
            "total_requested": len(sec_tasks),
            "completed": len([t for t in sec_tasks if t['status'] == 'done']),
            "skipped": len([t for t in sec_tasks if t['status'] == 'skipped']),
            "pending": len([t for t in sec_tasks if t['status'] == 'pending'])
        }
    return jsonify(report)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)