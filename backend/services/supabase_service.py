import os
import datetime
from supabase import create_client, Client

class SupabaseService:
    def __init__(self):
        self.url = os.environ.get("SUPABASE_URL")
        self.key = os.environ.get("SUPABASE_KEY")
        if not self.url or not self.key:
            raise ValueError("SUPABASE_URL and SUPABASE_KEY must be set in environment variables")
        self.client: Client = create_client(self.url, self.key)

    def _get_date_range(self, target_date_str=None):
        if target_date_str:
            try:
                # Expected format: YYYY-MM-DD
                target_date = datetime.datetime.strptime(target_date_str, "%Y-%m-%d")
                day_start = target_date.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=datetime.timezone.utc)
            except ValueError:
                now = datetime.datetime.now(datetime.timezone.utc)
                day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            now = datetime.datetime.now(datetime.timezone.utc)
            day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            
        day_end = day_start + datetime.timedelta(days=1)
        return day_start.isoformat(), day_end.isoformat(), day_start

    def create_shop(self, shop_name, owner_name, phone, password_hash):
        data = {
            "shop_name": shop_name,
            "owner_name": owner_name,
            "phone": phone,
            "password_hash": password_hash
        }
        res = self.client.table("shops").insert(data).execute()
        if len(res.data) == 0:
            return None
        return res.data[0]

    def get_shop_by_phone(self, phone):
        res = self.client.table("shops").select("*").eq("phone", phone).execute()
        if len(res.data) == 0:
            return None
        return res.data[0]

    def get_shop_by_id(self, shop_id):
        res = self.client.table("shops").select("*").eq("id", shop_id).execute()
        if len(res.data) == 0:
            return None
        return res.data[0]

    def join_queue(self, shop_id, name, phone, service_type="General Inquiry"):
        try:
            # Atomic operation using Supabase RPC database function
            res = self.client.rpc("join_shop_queue", {
                "p_shop_id": shop_id,
                "p_name": name,
                "p_phone": phone,
                "p_service_type": service_type
            }).execute()
            if len(res.data) > 0:
                return res.data[0]
        except Exception as e:
            # Fallback to direct Python select-then-insert
            # Find next token number
            res_max = self.client.table("queue") \
                .select("token_number") \
                .eq("shop_id", shop_id) \
                .order("token_number", desc=True) \
                .limit(1) \
                .execute()
            
            next_token = 1
            if len(res_max.data) > 0:
                next_token = res_max.data[0]["token_number"] + 1
            
            data = {
                "shop_id": shop_id,
                "name": name,
                "phone": phone,
                "token_number": next_token,
                "status": "waiting",
                "service_type": service_type
            }
            res_insert = self.client.table("queue").insert(data).execute()
            if len(res_insert.data) > 0:
                return res_insert.data[0]
        return None

    def get_queue_member(self, queue_id):
        res = self.client.table("queue").select("*").eq("id", queue_id).execute()
        if len(res.data) == 0:
            return None
        member = res.data[0]
        
        # Get shop info
        shop = self.get_shop_by_id(member["shop_id"])
        member["shop_name"] = shop["shop_name"] if shop else "Unknown Shop"
        
        # Get current serving token
        res_serving = self.client.table("queue") \
            .select("token_number") \
            .eq("shop_id", member["shop_id"]) \
            .eq("status", "serving") \
            .limit(1) \
            .execute()
        
        current_serving = None
        if len(res_serving.data) > 0:
            current_serving = res_serving.data[0]["token_number"]
        member["current_serving"] = current_serving
        
        # Get people ahead of them in queue
        res_ahead = self.client.table("queue") \
            .select("id", count="exact") \
            .eq("shop_id", member["shop_id"]) \
            .eq("status", "waiting") \
            .lt("token_number", member["token_number"]) \
            .execute()
        
        member["people_ahead"] = res_ahead.count if res_ahead.count is not None else 0
        return member

    def get_active_queue(self, shop_id, target_date=None):
        # Fetch active tokens (waiting and serving) for the target date
        start_iso, end_iso, _ = self._get_date_range(target_date)
        res = self.client.table("queue") \
            .select("*") \
            .eq("shop_id", shop_id) \
            .in_("status", ["waiting", "serving"]) \
            .gte("time_joined", start_iso) \
            .lt("time_joined", end_iso) \
            .order("token_number", desc=False) \
            .execute()
        return res.data

    def get_queue_history(self, shop_id, target_date=None):
        # Fetch completed/skipped history for the target date
        start_iso, end_iso, _ = self._get_date_range(target_date)
        res = self.client.table("queue") \
            .select("*") \
            .eq("shop_id", shop_id) \
            .in_("status", ["completed", "skipped"]) \
            .gte("time_joined", start_iso) \
            .lt("time_joined", end_iso) \
            .order("time_completed", desc=True) \
            .execute()
        return res.data

    def call_next(self, shop_id):
        try:
            # Atomic database operation
            res = self.client.rpc("call_next_customer", {
                "p_shop_id": shop_id
            }).execute()
            if len(res.data) > 0:
                return res.data[0]
        except Exception as e:
            # Fallback logic
            # Complete current serving customer
            res_curr = self.client.table("queue") \
                .select("id") \
                .eq("shop_id", shop_id) \
                .eq("status", "serving") \
                .limit(1) \
                .execute()
            
            completed_id = None
            if len(res_curr.data) > 0:
                completed_id = res_curr.data[0]["id"]
                now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
                self.client.table("queue") \
                    .update({"status": "completed", "time_completed": now_iso}) \
                    .eq("id", completed_id) \
                    .execute()
            
            # Serve next waiting customer
            res_next = self.client.table("queue") \
                .select("id", "token_number") \
                .eq("shop_id", shop_id) \
                .eq("status", "waiting") \
                .order("token_number", desc=False) \
                .limit(1) \
                .execute()
            
            serving_id = None
            serving_token = None
            if len(res_next.data) > 0:
                serving_id = res_next.data[0]["id"]
                serving_token = res_next.data[0]["token_number"]
                self.client.table("queue") \
                    .update({"status": "serving"}) \
                    .eq("id", serving_id) \
                    .execute()
            
            return {
                "completed_id": completed_id,
                "serving_id": serving_id,
                "serving_token": serving_token
            }
        return None

    def skip_customer(self, shop_id, queue_id):
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        res = self.client.table("queue") \
            .update({"status": "skipped", "time_completed": now_iso}) \
            .eq("id", queue_id) \
            .eq("shop_id", shop_id) \
            .execute()
        if len(res.data) == 0:
            return None
        return res.data[0]

    def reset_queue(self, shop_id):
        res = self.client.table("queue").delete().eq("shop_id", shop_id).execute()
        return True

    def submit_feedback(self, queue_id, rating, feedback_text):
        res = self.client.table("queue") \
            .update({"rating": rating, "feedback": feedback_text}) \
            .eq("id", queue_id) \
            .execute()
        if len(res.data) == 0:
            return None
        return res.data[0]

    def get_dashboard_analytics(self, shop_id, target_date=None):
        # Get start/end range of the selected target date
        start_iso, end_iso, day_start = self._get_date_range(target_date)
        
        # Total customers joined on this date
        res_total = self.client.table("queue") \
            .select("id", count="exact") \
            .eq("shop_id", shop_id) \
            .gte("time_joined", start_iso) \
            .lt("time_joined", end_iso) \
            .execute()
        total_count = res_total.count if res_total.count is not None else 0

        # Completed customers joined on this date
        res_completed = self.client.table("queue") \
            .select("id", count="exact") \
            .eq("shop_id", shop_id) \
            .eq("status", "completed") \
            .gte("time_joined", start_iso) \
            .lt("time_joined", end_iso) \
            .execute()
        completed_count = res_completed.count if res_completed.count is not None else 0

        # Skipped customers joined on this date
        res_skipped = self.client.table("queue") \
            .select("id", count="exact") \
            .eq("shop_id", shop_id) \
            .eq("status", "skipped") \
            .gte("time_joined", start_iso) \
            .lt("time_joined", end_iso) \
            .execute()
        skipped_count = res_skipped.count if res_skipped.count is not None else 0

        # Calculate average wait time (in minutes) for completed queue members on this date
        res_times = self.client.table("queue") \
            .select("time_joined, time_completed") \
            .eq("shop_id", shop_id) \
            .eq("status", "completed") \
            .gte("time_joined", start_iso) \
            .lt("time_joined", end_iso) \
            .execute()

        durations = []
        for row in res_times.data:
            if row.get("time_joined") and row.get("time_completed"):
                joined = datetime.datetime.fromisoformat(row["time_joined"].replace('Z', '+00:00'))
                completed = datetime.datetime.fromisoformat(row["time_completed"].replace('Z', '+00:00'))
                durations.append((completed - joined).total_seconds() / 60.0)
        
        avg_wait_time = round(sum(durations) / len(durations), 1) if len(durations) > 0 else 0.0

        # Calculate relative metrics relative to day_start of selected date
        yesterday_start = day_start - datetime.timedelta(days=1)
        yesterday_end = day_start
        res_yesterday = self.client.table("queue") \
            .select("id", count="exact") \
            .eq("shop_id", shop_id) \
            .eq("status", "completed") \
            .gte("time_completed", yesterday_start.isoformat()) \
            .lt("time_completed", yesterday_end.isoformat()) \
            .execute()
        yesterday_count = res_yesterday.count if res_yesterday.count is not None else 0

        # This Week calculation (starting from Monday of selected date's week)
        this_week_start = day_start - datetime.timedelta(days=day_start.weekday())
        res_this_week = self.client.table("queue") \
            .select("id", count="exact") \
            .eq("shop_id", shop_id) \
            .eq("status", "completed") \
            .gte("time_completed", this_week_start.isoformat()) \
            .lt("time_completed", end_iso) \
            .execute()
        this_week_count = res_this_week.count if res_this_week.count is not None else 0

        this_month_start = day_start.replace(day=1)
        res_this_month = self.client.table("queue") \
            .select("id", count="exact") \
            .eq("shop_id", shop_id) \
            .eq("status", "completed") \
            .gte("time_completed", this_month_start.isoformat()) \
            .lt("time_completed", end_iso) \
            .execute()
        this_month_count = res_this_month.count if res_this_month.count is not None else 0

        if this_month_start.month == 1:
            last_month_start = this_month_start.replace(year=this_month_start.year - 1, month=12)
        else:
            last_month_start = this_month_start.replace(month=this_month_start.month - 1)
        last_month_end = this_month_start

        res_last_month = self.client.table("queue") \
            .select("id", count="exact") \
            .eq("shop_id", shop_id) \
            .eq("status", "completed") \
            .gte("time_completed", last_month_start.isoformat()) \
            .lt("time_completed", last_month_end.isoformat()) \
            .execute()
        last_month_count = res_last_month.count if res_last_month.count is not None else 0

        # Feedback & Rating aggregation
        res_ratings = self.client.table("queue") \
            .select("rating") \
            .eq("shop_id", shop_id) \
            .not_.is_("rating", "null") \
            .execute()
        ratings = [row["rating"] for row in res_ratings.data if row.get("rating") is not None]
        avg_rating = round(sum(ratings) / len(ratings), 1) if len(ratings) > 0 else 0.0
        total_ratings = len(ratings)

        # Weekly traffic data (last 7 days leading to selected date)
        seven_days_ago = day_start - datetime.timedelta(days=6)
        res_seven_days = self.client.table("queue") \
            .select("time_completed") \
            .eq("shop_id", shop_id) \
            .eq("status", "completed") \
            .gte("time_completed", seven_days_ago.isoformat()) \
            .lt("time_completed", end_iso) \
            .execute()

        completed_dates = []
        for row in res_seven_days.data:
            if row.get("time_completed"):
                dt = datetime.datetime.fromisoformat(row["time_completed"].replace('Z', '+00:00'))
                completed_dates.append(dt.date())

        chart_data = []
        for i in range(6, -1, -1):
            d = (day_start - datetime.timedelta(days=i)).date()
            count = completed_dates.count(d)
            chart_data.append({
                "date": d.strftime("%a %b %d"),
                "count": count
            })

        return {
            "total_today": total_count,
            "completed_today": completed_count,
            "skipped_today": skipped_count,
            "avg_wait_time_minutes": avg_wait_time,
            "completed_yesterday": yesterday_count,
            "completed_this_week": this_week_count,
            "completed_this_month": this_month_count,
            "completed_last_month": last_month_count,
            "avg_rating": avg_rating,
            "total_ratings": total_ratings,
            "chart_data": chart_data
        }

    def get_export_data(self, shop_id, target_date=None):
        # Fetch all customers for export on the target date
        start_iso, end_iso, _ = self._get_date_range(target_date)
        res = self.client.table("queue") \
            .select("name, phone, token_number, status, time_joined") \
            .eq("shop_id", shop_id) \
            .gte("time_joined", start_iso) \
            .lt("time_joined", end_iso) \
            .order("token_number", desc=False) \
            .execute()
        return res.data
