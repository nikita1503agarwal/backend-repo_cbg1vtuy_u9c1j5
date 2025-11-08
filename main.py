import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from bson import ObjectId

from database import db, create_document, get_documents
from schemas import Customer, Vehicle, Inspection, Invoice

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Utilities

def to_obj_id(id_str: str) -> ObjectId:
    try:
        return ObjectId(id_str)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid ObjectId")


def serialize(doc: Dict[str, Any]):
    if not doc:
        return doc
    doc["_id"] = str(doc.get("_id"))
    return doc


@app.get("/")
def read_root():
    return {"message": "Car Inspection API running"}


# Seed demo data route
@app.post("/seed")
def seed_demo():
    # Create simple demo customers/vehicles if not exist
    existing = list(db["customer"].find({}).limit(1))
    if existing:
        return {"status": "ok", "message": "Already seeded"}

    alex_id = db["customer"].insert_one({"name": "Alex Johnson", "phone": "+1 555-101-2020", "email": "alex.j@example.com"}).inserted_id
    maria_id = db["customer"].insert_one({"name": "Maria Gomez", "phone": "+1 555-303-4040", "email": "maria.g@example.com"}).inserted_id

    db["vehicle"].insert_many([
        {"customer_id": str(alex_id), "vin": "1HGCM82633A004352", "plate": "AJX-4521", "make": "Honda", "model": "Civic", "year": 2018, "color": "Blue"},
        {"customer_id": str(alex_id), "vin": "1FTFW1ET1EKE12345", "plate": "TRK-9087", "make": "Ford", "model": "F-150", "year": 2014, "color": "Black"},
        {"customer_id": str(maria_id), "vin": "JH4KA4650MC123456", "plate": "MGM-2277", "make": "Acura", "model": "Legend", "year": 1991, "color": "Red"}
    ])

    return {"status": "ok", "message": "Seeded"}


# Search customers and vehicles
class SearchQuery(BaseModel):
    q: str


@app.post("/search")
def search(q: SearchQuery):
    query = q.q.strip()
    if not query:
        return {"results": []}

    regex = {"$regex": query, "$options": "i"}

    customers = list(db["customer"].find({"$or": [
        {"name": regex}, {"phone": regex}, {"email": regex}
    ]}))

    vehicles = list(db["vehicle"].find({"$or": [
        {"vin": regex}, {"plate": regex}, {"make": regex}, {"model": regex}
    ]}))

    # Map vehicles to their customers
    cust_map = {str(c["_id"]): c for c in customers}

    # Ensure customer for vehicles present
    missing_cust_ids = {v.get("customer_id") for v in vehicles} - set(cust_map.keys())
    if missing_cust_ids:
        extra_customers = list(db["customer"].find({"_id": {"$in": [to_obj_id(cid) for cid in missing_cust_ids if cid]}}))
        for c in extra_customers:
            cust_map[str(c["_id"])] = c

    # Group result by customer
    grouped = {}
    for v in vehicles:
        cid = v.get("customer_id")
        grouped.setdefault(cid, {"customer": cust_map.get(cid), "vehicles": []})
        grouped[cid]["vehicles"].append(v)

    # Also add customers with no vehicle matches but matched by customer fields
    for c in customers:
        cid = str(c["_id"])
        grouped.setdefault(cid, {"customer": c, "vehicles": list(db["vehicle"].find({"customer_id": cid}))})

    # Serialize
    results = []
    for cid, data in grouped.items():
        cust = serialize(data["customer"]) if data["customer"] else None
        vehs = [serialize(v) for v in data["vehicles"]]
        results.append({"customer": cust, "vehicles": vehs})

    return {"results": results}


# Create inspection and invoice
class InspectionPayload(BaseModel):
    customer_id: str
    vehicle_id: str
    checks: Dict[str, Dict[str, str]]
    notes: Optional[str] = None
    photos: Optional[List[str]] = []


@app.post("/inspections")
def create_inspection(payload: InspectionPayload):
    # Validate ids
    to_obj_id(payload.customer_id)
    to_obj_id(payload.vehicle_id)

    inspection = Inspection(
        customer_id=payload.customer_id,
        vehicle_id=payload.vehicle_id,
        checks=payload.checks,
        notes=payload.notes,
        photos=payload.photos or [],
    )
    ins_id = create_document("inspection", inspection)

    # Build invoice based on checks
    counts = {"attention": 0, "fail": 0}
    for section in inspection.checks.values():
        for v in section.values():
            if v == "attention":
                counts["attention"] += 1
            if v == "fail":
                counts["fail"] += 1

    line_items = []
    if counts["attention"]:
        line_items.append({"name": "Preventive maintenance items", "qty": counts["attention"], "price": 25.0})
    if counts["fail"]:
        line_items.append({"name": "Critical repair items", "qty": counts["fail"], "price": 60.0})
    line_items.append({"name": "Base inspection fee", "qty": 1, "price": 49.0})

    subtotal = sum(li["qty"] * li["price"] for li in line_items)
    taxes = round(subtotal * 0.08, 2)
    total = round(subtotal + taxes, 2)

    invoice = Invoice(
        inspection_id=ins_id,
        line_items=line_items,
        subtotal=subtotal,
        taxes=taxes,
        total=total,
        paid=False,
    )

    inv_id = create_document("invoice", invoice)

    return {"inspection_id": ins_id, "invoice_id": inv_id, "invoice": invoice.model_dump()}


# Pay invoice (simulate payment)
class PaymentPayload(BaseModel):
    invoice_id: str


@app.post("/pay")
def pay_invoice(payload: PaymentPayload):
    inv_id = to_obj_id(payload.invoice_id)
    result = db["invoice"].update_one({"_id": inv_id}, {"$set": {"paid": True}})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Invoice not found")
    doc = db["invoice"].find_one({"_id": inv_id})
    return serialize(doc)


@app.get("/schema")
def get_schema():
    # Let the admin UI introspect models if needed
    return {
        "collections": ["customer", "vehicle", "inspection", "invoice"],
    }


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }

    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Configured"
            response["database_name"] = db.name if hasattr(db, 'name') else "✅ Connected"
            response["connection_status"] = "Connected"

            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️  Connected but Error: {str(e)[:50]}"
        else:
            response["database"] = "⚠️  Available but not initialized"

    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"

    import os
    response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
    response["database_name"] = "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set"

    return response


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
