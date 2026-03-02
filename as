[35mapp/__init__.py[m[36m:[m[32m72[m[36m:[m        if "[1;31mfactory_id[m" not in session:
[35mapp/__init__.py[m[36m:[m[32m77[m[36m:[m                session["[1;31mfactory_id[m"] = first_factory.id
[35mapp/__init__.py[m[36m:[m[32m84[m[36m:[m                    session["[1;31mfactory_id[m"] = default_factory.id
[35mapp/auth_utils.py[m[36m:[m[32m33[m[36m:[m        if current_user.role == "admin" and current_user.[1;31mfactory_id[m is None:
[35mapp/auth_utils.py[m[36m:[m[32m37[m[36m:[m        target_factory = request.view_args.get("[1;31mfactory_id[m") \
[35mapp/auth_utils.py[m[36m:[m[32m38[m[36m:[m                        or request.form.get("[1;31mfactory_id[m") \
[35mapp/auth_utils.py[m[36m:[m[32m39[m[36m:[m                        or request.args.get("[1;31mfactory_id[m")
[35mapp/auth_utils.py[m[36m:[m[32m47[m[36m:[m            if target_factory != current_user.[1;31mfactory_id[m:
[35mapp/models.py[m[36m:[m[32m84[m[36m:[m    [1;31mfactory_id[m = db.Column(db.Integer, db.ForeignKey("factories.id"), nullable=True)
[35mapp/models.py[m[36m:[m[32m119[m[36m:[m        Superadmin can see all factories if [1;31mfactory_id[m is NULL.
[35mapp/models.py[m[36m:[m[32m120[m[36m:[m        Normal admins/managers have [1;31mfactory_id[m set.
[35mapp/models.py[m[36m:[m[32m122[m[36m:[m        return self.role == "admin" and self.[1;31mfactory_id[m is None
[35mapp/models.py[m[36m:[m[32m144[m[36m:[m    [1;31mfactory_id[m = db.Column(db.Integer, db.ForeignKey("factories.id"), nullable=False)
[35mapp/models.py[m[36m:[m[32m211[m[36m:[m    [1;31mfactory_id[m = db.Column(db.Integer, db.ForeignKey("factories.id"), nullable=False)
[35mapp/models.py[m[36m:[m[32m253[m[36m:[m        return f"<Product id={self.id} name={self.name!r} [1;31mfactory_id[m={self.[1;31mfactory_id[m}>"
[35mapp/models.py[m[36m:[m[32m344[m[36m:[m    [1;31mfactory_id[m = db.Column(db.Integer, db.ForeignKey("factories.id"), nullable=False)
[35mapp/models.py[m[36m:[m[32m353[m[36m:[m        return f"<CashRecord id={self.id} [1;31mfactory_id[m={self.[1;31mfactory_id[m} amount={self.amount} {self.currency}>"
[35mapp/models.py[m[36m:[m[32m366[m[36m:[m    [1;31mfactory_id[m = db.Column(db.Integer, db.ForeignKey("factories.id"), nullable=False)
[35mapp/models.py[m[36m:[m[32m403[m[36m:[m        return f"<ShopOrder id={self.id} status={self.status!r} [1;31mfactory_id[m={self.[1;31mfactory_id[m}>"
[35mapp/models.py[m[36m:[m[32m438[m[36m:[m    [1;31mfactory_id[m = db.Column(db.Integer, db.ForeignKey("factories.id"), nullable=False)
[35mapp/models.py[m[36m:[m[32m470[m[36m:[m    [1;31mfactory_id[m = db.Column(db.Integer, db.ForeignKey("factories.id"), nullable=False)
[35mapp/models.py[m[36m:[m[32m486[m[36m:[m            f"<Movement id={self.id} [1;31mfactory_id[m={self.[1;31mfactory_id[m} "
[35mapp/models.py[m[36m:[m[32m500[m[36m:[m    [1;31mfactory_id[m = db.Column(db.Integer, db.ForeignKey("factories.id"), nullable=False)
[35mapp/models.py[m[36m:[m[32m519[m[36m:[m        db.UniqueConstraint("[1;31mfactory_id[m", "file_hash", name="uq_excel_import_batch_filehash"),
[35mapp/models.py[m[36m:[m[32m523[m[36m:[m        return f"<ExcelImportBatch id={self.id} [1;31mfactory_id[m={self.[1;31mfactory_id[m} filename={self.filename!r} status={self.status!r}>"
[35mapp/models.py[m[36m:[m[32m534[m[36m:[m    [1;31mfactory_id[m = db.Column(db.Integer, db.ForeignKey("factories.id"), nullable=False)
[35mapp/models.py[m[36m:[m[32m542[m[36m:[m        db.UniqueConstraint("[1;31mfactory_id[m", "kind", "row_hash", name="uq_excel_import_row"),
[35mapp/models.py[m[36m:[m[32m546[m[36m:[m        return f"<ExcelImportRow id={self.id} [1;31mfactory_id[m={self.[1;31mfactory_id[m} kind={self.kind!r}>"
[35mapp/routes/accountant_report_routes.py[m[36m:[m[32m31[m[36m:[m    [1;31mfactory_id[m = current_user.[1;31mfactory_id[m
[35mapp/routes/accountant_report_routes.py[m[36m:[m[32m47[m[36m:[m        [1;31mfactory_id[m=[1;31mfactory_id[m,
[35mapp/routes/accountant_report_routes.py[m[36m:[m[32m52[m[36m:[m        [1;31mfactory_id[m=[1;31mfactory_id[m,
[35mapp/routes/cash_routes.py[m[36m:[m[32m16[m[36m:[m    [1;31mfactory_id[m = current_user.[1;31mfactory_id[m
[35mapp/routes/cash_routes.py[m[36m:[m[32m38[m[36m:[m    q = CashRecord.query.filter(CashRecord.[1;31mfactory_id[m == [1;31mfactory_id[m)
[35mapp/routes/cash_routes.py[m[36m:[m[32m62[m[36m:[m            Product.[1;31mfactory_id[m == [1;31mfactory_id[m,
[35mapp/routes/cash_routes.py[m[36m:[m[32m76[m[36m:[m            CashRecord.[1;31mfactory_id[m == [1;31mfactory_id[m,
[35mapp/routes/dashboard_routes.py[m[36m:[m[32m65[m[36m:[mdef _calc_cash_totals([1;31mfactory_id[m: int):
[35mapp/routes/dashboard_routes.py[m[36m:[m[32m66[m[36m:[m    records = CashRecord.query.filter_by([1;31mfactory_id[m=[1;31mfactory_id[m).all()
[35mapp/routes/dashboard_routes.py[m[36m:[m[32m72[m[36m:[mdef _get_production_today_summary([1;31mfactory_id[m: int):
[35mapp/routes/dashboard_routes.py[m[36m:[m[32m84[m[36m:[m        .filter(Product.[1;31mfactory_id[m == [1;31mfactory_id[m)
[35mapp/routes/dashboard_routes.py[m[36m:[m[32m96[m[36m:[mdef _get_shop_low_stock([1;31mfactory_id[m: int, threshold: int = 5, limit: int = 3):
[35mapp/routes/dashboard_routes.py[m[36m:[m[32m106[m[36m:[m        .filter(Product.[1;31mfactory_id[m == [1;31mfactory_id[m)
[35mapp/routes/dashboard_routes.py[m[36m:[m[32m119[m[36m:[mdef _get_yesterday_transfer_total([1;31mfactory_id[m: int):
[35mapp/routes/dashboard_routes.py[m[36m:[m[32m132[m[36m:[m        .filter(Movement.[1;31mfactory_id[m == [1;31mfactory_id[m)
[35mapp/routes/dashboard_routes.py[m[36m:[m[32m143[m[36m:[mdef _build_manager_dashboard([1;31mfactory_id[m: int):
[35mapp/routes/dashboard_routes.py[m[36m:[m[32m150[m[36m:[m    factory_uzs, factory_usd = product_service.total_stock_value([1;31mfactory_id[m=[1;31mfactory_id[m)
[35mapp/routes/dashboard_routes.py[m[36m:[m[32m151[m[36m:[m    shop_uzs, shop_usd = product_service.shop_stock_totals([1;31mfactory_id[m=[1;31mfactory_id[m)
[35mapp/routes/dashboard_routes.py[m[36m:[m[32m154[m[36m:[m    shop_low_stock_count, shop_low_stock_items = _get_shop_low_stock([1;31mfactory_id[m=[1;31mfactory_id[m)
[35mapp/routes/dashboard_routes.py[m[36m:[m[32m157[m[36m:[m    yesterday_transfer_total = _get_yesterday_transfer_total([1;31mfactory_id[m=[1;31mfactory_id[m)
[35mapp/routes/dashboard_routes.py[m[36m:[m[32m160[m[36m:[m    produced_today_total, produced_today_models, prod_today_rows = _get_production_today_summary([1;31mfactory_id[m)
[35mapp/routes/dashboard_routes.py[m[36m:[m[32m163[m[36m:[m    cash_total_uzs, cash_total_usd = _calc_cash_totals([1;31mfactory_id[m=[1;31mfactory_id[m)
[35mapp/routes/dashboard_routes.py[m[36m:[m[32m187[m[36m:[m    [1;31mfactory_id[m = current_user.[1;31mfactory_id[m
[35mapp/routes/dashboard_routes.py[m[36m:[m[32m190[m[36m:[m    data = _build_manager_dashboard([1;31mfactory_id[m=[1;31mfactory_id[m)
[35mapp/routes/fabric_report_routes.py[m[36m:[m[32m14[m[36m:[m    [1;31mfactory_id[m = current_user.[1;31mfactory_id[m
[35mapp/routes/fabric_report_routes.py[m[36m:[m[32m19[m[36m:[m        .filter_by([1;31mfactory_id[m=[1;31mfactory_id[m)
[35mapp/routes/fabric_routes.py[m[36m:[m[32m45[m[36m:[m    [1;31mfactory_id[m = current_user.[1;31mfactory_id[m
[35mapp/routes/fabric_routes.py[m[36m:[m[32m57[m[36m:[m            [1;31mfactory_id[m=[1;31mfactory_id[m,
[35mapp/routes/fabric_routes.py[m[36m:[m[32m68[m[36m:[m            [1;31mfactory_id[m=[1;31mfactory_id[m,
[35mapp/routes/fabric_routes.py[m[36m:[m[32m72[m[36m:[m    cuts = service.recent_cuts([1;31mfactory_id[m=[1;31mfactory_id[m)
[35mapp/routes/fabric_routes.py[m[36m:[m[32m73[m[36m:[m    categories = service.get_categories([1;31mfactory_id[m=[1;31mfactory_id[m)
[35mapp/routes/fabric_routes.py[m[36m:[m[32m76[m[36m:[m    fabric_stats = service.get_dashboard_stats([1;31mfactory_id[m=[1;31mfactory_id[m)
[35mapp/routes/fabric_routes.py[m[36m:[m[32m147[m[36m:[m        [1;31mfactory_id[m=current_user.[1;31mfactory_id[m,
[35mapp/routes/fabric_routes.py[m[36m:[m[32m193[m[36m:[m        [1;31mfactory_id[m=current_user.[1;31mfactory_id[m,
[35mapp/routes/fabric_routes.py[m[36m:[m[32m231[m[36m:[m        [1;31mfactory_id[m=current_user.[1;31mfactory_id[m,
[35mapp/routes/fabric_routes.py[m[36m:[m[32m260[m[36m:[m        [1;31mfactory_id[m=current_user.[1;31mfactory_id[m,
[35mapp/routes/fabric_routes.py[m[36m:[m[32m292[m[36m:[m    csv_bytes = service.export_csv([1;31mfactory_id[m=current_user.[1;31mfactory_id[m)
[35mapp/routes/fabric_routes.py[m[36m:[m[32m307[m[36m:[m        .filter_by(id=fabric_id, [1;31mfactory_id[m=current_user.[1;31mfactory_id[m)
[35mapp/routes/fabric_routes.py[m[36m:[m[32m359[m[36m:[m    q_base = Cut.query.join(Fabric).filter(Fabric.[1;31mfactory_id[m == current_user.[1;31mfactory_id[m)
[35mapp/routes/fabric_routes.py[m[36m:[m[32m371[m[36m:[m            .filter_by(id=fabric_id, [1;31mfactory_id[m=current_user.[1;31mfactory_id[m)
[35mapp/routes/fabric_routes.py[m[36m:[m[32m431[m[36m:[m        .filter(Fabric.[1;31mfactory_id[m == current_user.[1;31mfactory_id[m)
[35mapp/routes/fabric_routes.py[m[36m:[m[32m483[m[36m:[m        [1;31mfactory_id[m=current_user.[1;31mfactory_id[m,
[35mapp/routes/factory_routes.py[m[36m:[m[32m109[m[36m:[mdef _get_categories_for_factory([1;31mfactory_id[m: int) -> list[str]:
[35mapp/routes/factory_routes.py[m[36m:[m[32m112[m[36m:[m        .filter(Product.[1;31mfactory_id[m == [1;31mfactory_id[m)
[35mapp/routes/factory_routes.py[m[36m:[m[32m122[m[36m:[mdef _build_today_map([1;31mfactory_id[m: int):
[35mapp/routes/factory_routes.py[m[36m:[m[32m129[m[36m:[m        .filter(Product.[1;31mfactory_id[m == [1;31mfactory_id[m)
[35mapp/routes/factory_routes.py[m[36m:[m[32m146[m[36m:[m    [1;31mfactory_id[m = current_user.[1;31mfactory_id[m
[35mapp/routes/factory_routes.py[m[36m:[m[32m151[m[36m:[m    query = Product.query.filter(Product.[1;31mfactory_id[m == [1;31mfactory_id[m)
[35mapp/routes/factory_routes.py[m[36m:[m[32m170[m[36m:[m    categories = _get_categories_for_factory([1;31mfactory_id[m)
[35mapp/routes/factory_routes.py[m[36m:[m[32m171[m[36m:[m    today_map, today_total = _build_today_map([1;31mfactory_id[m)
[35mapp/routes/factory_routes.py[m[36m:[m[32m194[m[36m:[m    [1;31mfactory_id[m = current_user.[1;31mfactory_id[m
[35mapp/routes/factory_routes.py[m[36m:[m[32m199[m[36m:[m        .filter(Product.[1;31mfactory_id[m == [1;31mfactory_id[m)
[35mapp/routes/factory_routes.py[m[36m:[m[32m260[m[36m:[m    [1;31mfactory_id[m = current_user.[1;31mfactory_id[m
[35mapp/routes/factory_routes.py[m[36m:[m[32m278[m[36m:[m        .filter(Product.[1;31mfactory_id[m == [1;31mfactory_id[m, Product.id.in_(ids))
[35mapp/routes/factory_routes.py[m[36m:[m[32m320[m[36m:[m    [1;31mfactory_id[m = current_user.[1;31mfactory_id[m
[35mapp/routes/factory_routes.py[m[36m:[m[32m343[m[36m:[m        product = Product.query.filter_by(id=product_id, [1;31mfactory_id[m=[1;31mfactory_id[m).first()
[35mapp/routes/factory_routes.py[m[36m:[m[32m351[m[36m:[m                [1;31mfactory_id[m=[1;31mfactory_id[m,
[35mapp/routes/factory_routes.py[m[36m:[m[32m358[m[36m:[m                [1;31mfactory_id[m=[1;31mfactory_id[m,
[35mapp/routes/factory_routes.py[m[36m:[m[32m410[m[36m:[m    [1;31mfactory_id[m = current_user.[1;31mfactory_id[m
[35mapp/routes/factory_routes.py[m[36m:[m[32m425[m[36m:[m    base_query = Product.query.filter(Product.[1;31mfactory_id[m == [1;31mfactory_id[m)
[35mapp/routes/manager_report_routes.py[m[36m:[m[32m16[m[36m:[m    [1;31mfactory_id[m = current_user.[1;31mfactory_id[m
[35mapp/routes/manager_report_routes.py[m[36m:[m[32m17[m[36m:[m    report = product_service.get_manager_financial_report([1;31mfactory_id[m=[1;31mfactory_id[m)
[35mapp/routes/manager_report_routes.py[m[36m:[m[32m24[m[36m:[m    [1;31mfactory_id[m = current_user.[1;31mfactory_id[m
[35mapp/routes/manager_report_routes.py[m[36m:[m[32m25[m[36m:[m    report = product_service.get_manager_financial_report([1;31mfactory_id[m=[1;31mfactory_id[m)
[35mapp/routes/product_routes.py[m[36m:[m[32m70[m[36m:[m        return current_user.[1;31mfactory_id[m  # may be None
[35mapp/routes/product_routes.py[m[36m:[m[32m71[m[36m:[m    if current_user.[1;31mfactory_id[m is None:
[35mapp/routes/product_routes.py[m[36m:[m[32m74[m[36m:[m    return current_user.[1;31mfactory_id[m
[35mapp/routes/product_routes.py[m[36m:[m[32m81[m[36m:[mdef _import_folder([1;31mfactory_id[m: int) -> tuple[str, str]:
[35mapp/routes/product_routes.py[m[36m:[m[32m83[m[36m:[m    rel_dir = os.path.join("uploads", "excel_imports", str([1;31mfactory_id[m))
[35mapp/routes/product_routes.py[m[36m:[m[32m113[m[36m:[mdef _already_imported([1;31mfactory_id[m: int, kind: str, row_hash: str) -> bool:
[35mapp/routes/product_routes.py[m[36m:[m[32m115[m[36m:[m        [1;31mfactory_id[m=[1;31mfactory_id[m, kind=kind, row_hash=row_hash
[35mapp/routes/product_routes.py[m[36m:[m[32m119[m[36m:[mdef _mark_imported([1;31mfactory_id[m: int, kind: str, row_hash: str) -> None:
[35mapp/routes/product_routes.py[m[36m:[m[32m120[m[36m:[m    db.session.add(ExcelImportRow([1;31mfactory_id[m=[1;31mfactory_id[m, kind=kind, row_hash=row_hash))
[35mapp/routes/product_routes.py[m[36m:[m[32m142[m[36m:[m    [1;31mfactory_id[m = current_user.[1;31mfactory_id[m
[35mapp/routes/product_routes.py[m[36m:[m[32m153[m[36m:[m        query = query.filter(Product.[1;31mfactory_id[m == [1;31mfactory_id[m)
[35mapp/routes/product_routes.py[m[36m:[m[32m182[m[36m:[m        cat_query = cat_query.filter(Product.[1;31mfactory_id[m == [1;31mfactory_id[m)
[35mapp/routes/product_routes.py[m[36m:[m[32m203[m[36m:[m    [1;31mfactory_id[m = _ensure_factory_bound()
[35mapp/routes/product_routes.py[m[36m:[m[32m204[m[36m:[m    if [1;31mfactory_id[m is None and not getattr(current_user, "is_superadmin", False):
[35mapp/routes/product_routes.py[m[36m:[m[32m237[m[36m:[m        [1;31mfactory_id[m=[1;31mfactory_id[m,
[35mapp/routes/product_routes.py[m[36m:[m[32m258[m[36m:[m    [1;31mfactory_id[m = _ensure_factory_bound()
[35mapp/routes/product_routes.py[m[36m:[m[32m259[m[36m:[m    if [1;31mfactory_id[m is None and not getattr(current_user, "is_superadmin", False):
[35mapp/routes/product_routes.py[m[36m:[m[32m267[m[36m:[m    service.increase_stock([1;31mfactory_id[m=[1;31mfactory_id[m, product_id=product_id, quantity=quantity)
[35mapp/routes/product_routes.py[m[36m:[m[32m279[m[36m:[m    [1;31mfactory_id[m = _ensure_factory_bound()
[35mapp/routes/product_routes.py[m[36m:[m[32m280[m[36m:[m    if [1;31mfactory_id[m is None and not getattr(current_user, "is_superadmin", False):
[35mapp/routes/product_routes.py[m[36m:[m[32m294[m[36m:[m            [1;31mfactory_id[m=[1;31mfactory_id[m,
[35mapp/routes/product_routes.py[m[36m:[m[32m315[m[36m:[m    [1;31mfactory_id[m = _ensure_factory_bound()
[35mapp/routes/product_routes.py[m[36m:[m[32m316[m[36m:[m    if [1;31mfactory_id[m is None and not getattr(current_user, "is_superadmin", False):
[35mapp/routes/product_routes.py[m[36m:[m[32m325[m[36m:[m        service.transfer_to_shop([1;31mfactory_id[m=[1;31mfactory_id[m, product_id=product_id, quantity=quantity)
[35mapp/routes/product_routes.py[m[36m:[m[32m341[m[36m:[m    [1;31mfactory_id[m = _ensure_factory_bound()
[35mapp/routes/product_routes.py[m[36m:[m[32m342[m[36m:[m    if [1;31mfactory_id[m is None:
[35mapp/routes/product_routes.py[m[36m:[m[32m348[m[36m:[m        .filter_by([1;31mfactory_id[m=[1;31mfactory_id[m)
[35mapp/routes/product_routes.py[m[36m:[m[32m360[m[36m:[m    [1;31mfactory_id[m = _ensure_factory_bound()
[35mapp/routes/product_routes.py[m[36m:[m[32m361[m[36m:[m    if [1;31mfactory_id[m is None:
[35mapp/routes/product_routes.py[m[36m:[m[32m378[m[36m:[m    existing = ExcelImportBatch.query.filter_by([1;31mfactory_id[m=[1;31mfactory_id[m, file_hash=file_hash).first()
[35mapp/routes/product_routes.py[m[36m:[m[32m384[m[36m:[m    rel_dir, abs_dir = _import_folder([1;31mfactory_id[m)  # must return (rel_dir, abs_dir)
[35mapp/routes/product_routes.py[m[36m:[m[32m396[m[36m:[m        [1;31mfactory_id[m=[1;31mfactory_id[m,
[35mapp/routes/product_routes.py[m[36m:[m[32m439[m[36m:[m    [1;31mfactory_id[m = _ensure_factory_bound()
[35mapp/routes/product_routes.py[m[36m:[m[32m440[m[36m:[m    if [1;31mfactory_id[m is None:
[35mapp/routes/product_routes.py[m[36m:[m[32m445[m[36m:[m    batch = ExcelImportBatch.query.filter_by(id=batch_id, [1;31mfactory_id[m=[1;31mfactory_id[m).first()
[35mapp/routes/product_routes.py[m[36m:[m[32m500[m[36m:[m                    [1;31mfactory_id[m=[1;31mfactory_id[m,
[35mapp/routes/product_routes.py[m[36m:[m[32m510[m[36m:[m                s2 = _import_sheet_cash(raw=raw, [1;31mfactory_id[m=[1;31mfactory_id[m, sheet_name=sheet)
[35mapp/routes/product_routes.py[m[36m:[m[32m543[m[36m:[m    [1;31mfactory_id[m = _ensure_factory_bound()
[35mapp/routes/product_routes.py[m[36m:[m[32m544[m[36m:[m    if [1;31mfactory_id[m is None:
[35mapp/routes/product_routes.py[m[36m:[m[32m547[m[36m:[m    batch = ExcelImportBatch.query.filter_by(id=batch_id, [1;31mfactory_id[m=[1;31mfactory_id[m).first_or_404()
[35mapp/routes/product_routes.py[m[36m:[m[32m604[m[36m:[mdef _import_sheet_realization(raw: pd.DataFrame, [1;31mfactory_id[m: int, sheet_name: str, do_sales: bool, update_prices: bool):
[35mapp/routes/product_routes.py[m[36m:[m[32m666[m[36m:[m        product = Product.query.filter_by([1;31mfactory_id[m=[1;31mfactory_id[m, name=model).first()
[35mapp/routes/product_routes.py[m[36m:[m[32m668[m[36m:[m            product = Product([1;31mfactory_id[m=[1;31mfactory_id[m, name=model)
[35mapp/routes/product_routes.py[m[36m:[m[32m681[m[36m:[m            if _already_imported([1;31mfactory_id[m, "sale", sale_hash):
[35mapp/routes/product_routes.py[m[36m:[m[32m702[m[36m:[m                    [1;31mfactory_id[m=[1;31mfactory_id[m,
[35mapp/routes/product_routes.py[m[36m:[m[32m712[m[36m:[m            _mark_imported([1;31mfactory_id[m, "sale", sale_hash)
[35mapp/routes/product_routes.py[m[36m:[m[32m718[m[36m:[mdef _import_sheet_cash(raw: pd.DataFrame, [1;31mfactory_id[m: int, sheet_name: str):
[35mapp/routes/product_routes.py[m[36m:[m[32m774[m[36m:[m        if _already_imported([1;31mfactory_id[m, "cash", cash_hash):
[35mapp/routes/product_routes.py[m[36m:[m[32m779[m[36m:[m                [1;31mfactory_id[m=[1;31mfactory_id[m,
[35mapp/routes/product_routes.py[m[36m:[m[32m786[m[36m:[m        _mark_imported([1;31mfactory_id[m, "cash", cash_hash)
[35mapp/routes/sale_routes.py[m[36m:[m[32m30[m[36m:[m    [1;31mfactory_id[m = current_user.[1;31mfactory_id[m
[35mapp/routes/sale_routes.py[m[36m:[m[32m31[m[36m:[m    if not [1;31mfactory_id[m:
[35mapp/routes/sale_routes.py[m[36m:[m[32m32[m[36m:[m        flash("Ошибка: у пользователя нет [1;31mfactory_id[m", "danger")
[35mapp/routes/sale_routes.py[m[36m:[m[32m78[m[36m:[m                [1;31mfactory_id[m=[1;31mfactory_id[m,
[35mapp/routes/sale_routes.py[m[36m:[m[32m84[m[36m:[m                    [1;31mfactory_id[m=[1;31mfactory_id[m,
[35mapp/routes/sale_routes.py[m[36m:[m[32m93[m[36m:[m                [1;31mfactory_id[m=[1;31mfactory_id[m,
[35mapp/routes/sale_routes.py[m[36m:[m[32m101[m[36m:[m                    [1;31mfactory_id[m=[1;31mfactory_id[m,
[35mapp/routes/sale_routes.py[m[36m:[m[32m116[m[36m:[m                    [1;31mfactory_id[m=[1;31mfactory_id[m,
[35mapp/routes/sale_routes.py[m[36m:[m[32m171[m[36m:[m        .filter(Product.[1;31mfactory_id[m == current_user.[1;31mfactory_id[m)
[35mapp/routes/sale_routes.py[m[36m:[m[32m222[m[36m:[m    [1;31mfactory_id[m = current_user.[1;31mfactory_id[m
[35mapp/routes/sale_routes.py[m[36m:[m[32m227[m[36m:[m        .filter_by([1;31mfactory_id[m=[1;31mfactory_id[m)
[35mapp/routes/sale_routes.py[m[36m:[m[32m257[m[36m:[m                [1;31mfactory_id[m=[1;31mfactory_id[m,
[35mapp/routes/shop_monthly_routes.py[m[36m:[m[32m14[m[36m:[m    data = product_service.get_monthly_report([1;31mfactory_id[m=current_user.[1;31mfactory_id[m)
[35mapp/routes/shop_report_routes.py[m[36m:[m[32m11[m[36m:[m    data = product_service.weekly_shop_report([1;31mfactory_id[m=current_user.[1;31mfactory_id[m)
[35mapp/routes/shop_routes.py[m[36m:[m[32m48[m[36m:[m        [1;31mfactory_id[m=current_user.[1;31mfactory_id[m,
[35mapp/routes/shop_routes.py[m[36m:[m[32m68[m[36m:[m    [1;31mfactory_id[m = current_user.[1;31mfactory_id[m
[35mapp/routes/shop_routes.py[m[36m:[m[32m90[m[36m:[m            .filter_by(id=product_id, [1;31mfactory_id[m=[1;31mfactory_id[m)
[35mapp/routes/shop_routes.py[m[36m:[m[32m99[m[36m:[m                [1;31mfactory_id[m=[1;31mfactory_id[m,
[35mapp/routes/shop_routes.py[m[36m:[m[32m109[m[36m:[m            [1;31mfactory_id[m=[1;31mfactory_id[m,
[35mapp/routes/shop_routes.py[m[36m:[m[32m129[m[36m:[m            .filter_by([1;31mfactory_id[m=[1;31mfactory_id[m)
[35mapp/routes/shop_routes.py[m[36m:[m[32m137[m[36m:[m            .filter(Product.[1;31mfactory_id[m == [1;31mfactory_id[m)
[35mapp/routes/shop_routes.py[m[36m:[m[32m148[m[36m:[m                    Product.[1;31mfactory_id[m == [1;31mfactory_id[m,
[35mapp/routes/shop_routes.py[m[36m:[m[32m158[m[36m:[m                    Product.[1;31mfactory_id[m == [1;31mfactory_id[m,
[35mapp/routes/shop_routes.py[m[36m:[m[32m179[m[36m:[m        [1;31mfactory_id[m=current_user.[1;31mfactory_id[m,
[35mapp/routes/shop_routes.py[m[36m:[m[32m198[m[36m:[m    [1;31mfactory_id[m = current_user.[1;31mfactory_id[m
[35mapp/routes/shop_routes.py[m[36m:[m[32m201[m[36m:[m    query = ShopOrder.query.filter_by([1;31mfactory_id[m=[1;31mfactory_id[m)
[35mapp/routes/shop_routes.py[m[36m:[m[32m211[m[36m:[m    base_query = ShopOrder.query.filter_by([1;31mfactory_id[m=[1;31mfactory_id[m)
[35mapp/routes/shop_routes.py[m[36m:[m[32m234[m[36m:[m    [1;31mfactory_id[m = current_user.[1;31mfactory_id[m
[35mapp/routes/shop_routes.py[m[36m:[m[32m238[m[36m:[m        .filter_by(id=order_id, [1;31mfactory_id[m=[1;31mfactory_id[m)
[35mapp/routes/shop_routes.py[m[36m:[m[32m270[m[36m:[m        .filter_by([1;31mfactory_id[m=current_user.[1;31mfactory_id[m, status="pending")
[35mapp/routes/shop_routes.py[m[36m:[m[32m281[m[36m:[m    [1;31mfactory_id[m = current_user.[1;31mfactory_id[m
[35mapp/routes/shop_routes.py[m[36m:[m[32m288[m[36m:[m            Product.[1;31mfactory_id[m == [1;31mfactory_id[m,
[35mapp/routes/shop_routes.py[m[36m:[m[32m328[m[36m:[m        [1;31mfactory_id[m=[1;31mfactory_id[m,
[35mapp/routes/shop_routes.py[m[36m:[m[32m340[m[36m:[m        [1;31mfactory_id[m=[1;31mfactory_id[m,
[35mapp/routes/shop_routes.py[m[36m:[m[32m360[m[36m:[m    [1;31mfactory_id[m = current_user.[1;31mfactory_id[m
[35mapp/routes/shop_routes.py[m[36m:[m[32m386[m[36m:[m        .filter(Product.[1;31mfactory_id[m == [1;31mfactory_id[m)
[35mapp/routes/shop_routes.py[m[36m:[m[32m413[m[36m:[m        .filter_by([1;31mfactory_id[m=[1;31mfactory_id[m)
[35mapp/routes/shop_routes.py[m[36m:[m[32m437[m[36m:[m            Product.[1;31mfactory_id[m == current_user.[1;31mfactory_id[m,
[35mapp/routes/shop_routes.py[m[36m:[m[32m458[m[36m:[m        .filter_by(id=order_id, [1;31mfactory_id[m=current_user.[1;31mfactory_id[m)
[35mapp/routes/shop_routes.py[m[36m:[m[32m466[m[36m:[m            StockMovement.[1;31mfactory_id[m == current_user.[1;31mfactory_id[m,
[35mapp/routes/shop_routes.py[m[36m:[m[32m483[m[36m:[m    [1;31mfactory_id[m = current_user.[1;31mfactory_id[m
[35mapp/routes/shop_routes.py[m[36m:[m[32m487[m[36m:[m        .filter_by(id=product_id, [1;31mfactory_id[m=[1;31mfactory_id[m)
[35mapp/routes/shop_routes.py[m[36m:[m[32m511[m[36m:[m                [1;31mfactory_id[m=[1;31mfactory_id[m,
[35mapp/routes/shop_routes.py[m[36m:[m[32m531[m[36m:[m                [1;31mfactory_id[m=[1;31mfactory_id[m,
[35mapp/services/cash_service.py[m[36m:[m[32m7[m[36m:[m    def list_records(self, date_from=None, date_to=None, [1;31mfactory_id[m: int | None = None):
[35mapp/services/cash_service.py[m[36m:[m[32m10[m[36m:[m        if [1;31mfactory_id[m is not None:
[35mapp/services/cash_service.py[m[36m:[m[32m11[m[36m:[m            q = q.filter(CashRecord.[1;31mfactory_id[m == [1;31mfactory_id[m)
[35mapp/services/cash_service.py[m[36m:[m[32m20[m[36m:[m    def totals(self, date_from=None, date_to=None, [1;31mfactory_id[m: int | None = None):
[35mapp/services/cash_service.py[m[36m:[m[32m23[m[36m:[m        if [1;31mfactory_id[m is not None:
[35mapp/services/cash_service.py[m[36m:[m[32m24[m[36m:[m            q = q.filter(CashRecord.[1;31mfactory_id[m == [1;31mfactory_id[m)
[35mapp/services/cash_service.py[m[36m:[m[32m42[m[36m:[m    def today_totals(self, [1;31mfactory_id[m: int | None = None):
[35mapp/services/cash_service.py[m[36m:[m[32m44[m[36m:[m        return self.totals(date_from=today, date_to=today, [1;31mfactory_id[m=[1;31mfactory_id[m)
[35mapp/services/fabric_service.py[m[36m:[m[32m40[m[36m:[m        [1;31mfactory_id[m: int | None = None,
[35mapp/services/fabric_service.py[m[36m:[m[32m48[m[36m:[m        if [1;31mfactory_id[m is not None:
[35mapp/services/fabric_service.py[m[36m:[m[32m49[m[36m:[m            q = q.filter(Fabric.[1;31mfactory_id[m == [1;31mfactory_id[m)
[35mapp/services/fabric_service.py[m[36m:[m[32m88[m[36m:[m    def recent_cuts(self, limit: int = 10, [1;31mfactory_id[m: int | None = None):
[35mapp/services/fabric_service.py[m[36m:[m[32m93[m[36m:[m        if [1;31mfactory_id[m is not None:
[35mapp/services/fabric_service.py[m[36m:[m[32m94[m[36m:[m            q = q.filter(Fabric.[1;31mfactory_id[m == [1;31mfactory_id[m)
[35mapp/services/fabric_service.py[m[36m:[m[32m113[m[36m:[m        [1;31mfactory_id[m: int,
[35mapp/services/fabric_service.py[m[36m:[m[32m127[m[36m:[m            Fabric.[1;31mfactory_id[m == [1;31mfactory_id[m,
[35mapp/services/fabric_service.py[m[36m:[m[32m173[m[36m:[m                "[1;31mfactory_id[m": [1;31mfactory_id[m,
[35mapp/services/fabric_service.py[m[36m:[m[32m179[m[36m:[m            [1;31mfactory_id[m=[1;31mfactory_id[m,
[35mapp/services/fabric_service.py[m[36m:[m[32m199[m[36m:[m        [1;31mfactory_id[m: int,
[35mapp/services/fabric_service.py[m[36m:[m[32m206[m[36m:[m            .filter_by(id=existing_id, [1;31mfactory_id[m=[1;31mfactory_id[m)
[35mapp/services/fabric_service.py[m[36m:[m[32m232[m[36m:[m        [1;31mfactory_id[m: int,
[35mapp/services/fabric_service.py[m[36m:[m[32m238[m[36m:[m            [1;31mfactory_id[m=[1;31mfactory_id[m,
[35mapp/services/fabric_service.py[m[36m:[m[32m253[m[36m:[m    def get_categories(self, [1;31mfactory_id[m: int | None = None):
[35mapp/services/fabric_service.py[m[36m:[m[32m261[m[36m:[m        if [1;31mfactory_id[m is not None:
[35mapp/services/fabric_service.py[m[36m:[m[32m262[m[36m:[m            q = q.filter(Fabric.[1;31mfactory_id[m == [1;31mfactory_id[m)
[35mapp/services/fabric_service.py[m[36m:[m[32m271[m[36m:[m    def get_dashboard_stats(self, [1;31mfactory_id[m: int | None = None):
[35mapp/services/fabric_service.py[m[36m:[m[32m282[m[36m:[m        if [1;31mfactory_id[m is not None:
[35mapp/services/fabric_service.py[m[36m:[m[32m283[m[36m:[m            q = q.filter(Fabric.[1;31mfactory_id[m == [1;31mfactory_id[m)
[35mapp/services/fabric_service.py[m[36m:[m[32m327[m[36m:[m    def export_csv(self, [1;31mfactory_id[m: int | None = None) -> bytes:
[35mapp/services/fabric_service.py[m[36m:[m[32m339[m[36m:[m        if [1;31mfactory_id[m is not None:
[35mapp/services/fabric_service.py[m[36m:[m[32m340[m[36m:[m            q = q.filter(Fabric.[1;31mfactory_id[m == [1;31mfactory_id[m)
[35mapp/services/fabric_service.py[m[36m:[m[32m360[m[36m:[m    def cut_fabric(self, fabric_id: int, used_amount: float, [1;31mfactory_id[m: int) -> bool:
[35mapp/services/fabric_service.py[m[36m:[m[32m370[m[36m:[m            .filter_by(id=fabric_id, [1;31mfactory_id[m=[1;31mfactory_id[m)
[35mapp/services/fabric_service.py[m[36m:[m[32m395[m[36m:[m        [1;31mfactory_id[m: int | None = None,
[35mapp/services/fabric_service.py[m[36m:[m[32m414[m[36m:[m        if [1;31mfactory_id[m is not None:
[35mapp/services/fabric_service.py[m[36m:[m[32m415[m[36m:[m            qy = qy.filter(Fabric.[1;31mfactory_id[m == [1;31mfactory_id[m)
[35mapp/services/fabric_service.py[m[36m:[m[32m451[m[36m:[m        [1;31mfactory_id[m: int | None = None,
[35mapp/services/fabric_service.py[m[36m:[m[32m460[m[36m:[m        if [1;31mfactory_id[m is not None:
[35mapp/services/fabric_service.py[m[36m:[m[32m461[m[36m:[m            q = q.filter(Fabric.[1;31mfactory_id[m == [1;31mfactory_id[m)
[35mapp/services/fabric_service.py[m[36m:[m[32m490[m[36m:[m    def latest_fabrics(self, limit: int = 5, [1;31mfactory_id[m: int | None = None):
[35mapp/services/fabric_service.py[m[36m:[m[32m496[m[36m:[m        if [1;31mfactory_id[m is not None:
[35mapp/services/fabric_service.py[m[36m:[m[32m497[m[36m:[m            q = q.filter(Fabric.[1;31mfactory_id[m == [1;31mfactory_id[m)
[35mapp/services/product_service.py[m[36m:[m[32m16[m[36m:[m        [1;31mfactory_id[m: int | None = None,
[35mapp/services/product_service.py[m[36m:[m[32m19[m[36m:[m        if [1;31mfactory_id[m is not None:
[35mapp/services/product_service.py[m[36m:[m[32m20[m[36m:[m            q = q.filter(Product.[1;31mfactory_id[m == [1;31mfactory_id[m)
[35mapp/services/product_service.py[m[36m:[m[32m36[m[36m:[m    def get_categories(self, [1;31mfactory_id[m: int | None = None):
[35mapp/services/product_service.py[m[36m:[m[32m41[m[36m:[m        if [1;31mfactory_id[m is not None:
[35mapp/services/product_service.py[m[36m:[m[32m42[m[36m:[m            q = q.filter(Product.[1;31mfactory_id[m == [1;31mfactory_id[m)
[35mapp/services/product_service.py[m[36m:[m[32m53[m[36m:[m        [1;31mfactory_id[m: int,
[35mapp/services/product_service.py[m[36m:[m[32m70[m[36m:[m                Product.[1;31mfactory_id[m == [1;31mfactory_id[m,
[35mapp/services/product_service.py[m[36m:[m[32m115[m[36m:[m            [1;31mfactory_id[m=[1;31mfactory_id[m,
[35mapp/services/product_service.py[m[36m:[m[32m138[m[36m:[m    def increase_stock(self, [1;31mfactory_id[m: int, product_id: int, quantity: int):
[35mapp/services/product_service.py[m[36m:[m[32m141[m[36m:[m            .filter_by(id=product_id, [1;31mfactory_id[m=[1;31mfactory_id[m)
[35mapp/services/product_service.py[m[36m:[m[32m152[m[36m:[m        [1;31mfactory_id[m: int,
[35mapp/services/product_service.py[m[36m:[m[32m161[m[36m:[m            .filter_by(id=product_id, [1;31mfactory_id[m=[1;31mfactory_id[m)
[35mapp/services/product_service.py[m[36m:[m[32m167[m[36m:[m        shop_stock = self._get_or_create_shop_stock(product_id, [1;31mfactory_id[m)
[35mapp/services/product_service.py[m[36m:[m[32m201[m[36m:[m            [1;31mfactory_id[m=[1;31mfactory_id[m,
[35mapp/services/product_service.py[m[36m:[m[32m209[m[36m:[m    def recent_sales(self, limit: int = 20, [1;31mfactory_id[m: int | None = None):
[35mapp/services/product_service.py[m[36m:[m[32m211[m[36m:[m        if [1;31mfactory_id[m is not None:
[35mapp/services/product_service.py[m[36m:[m[32m212[m[36m:[m            q = q.filter(Product.[1;31mfactory_id[m == [1;31mfactory_id[m)
[35mapp/services/product_service.py[m[36m:[m[32m220[m[36m:[m    def total_stock_value(self, [1;31mfactory_id[m: int | None = None):
[35mapp/services/product_service.py[m[36m:[m[32m222[m[36m:[m        if [1;31mfactory_id[m is not None:
[35mapp/services/product_service.py[m[36m:[m[32m223[m[36m:[m            q = q.filter(Product.[1;31mfactory_id[m == [1;31mfactory_id[m)
[35mapp/services/product_service.py[m[36m:[m[32m236[m[36m:[m    def sales_totals(self, [1;31mfactory_id[m: int | None = None):
[35mapp/services/product_service.py[m[36m:[m[32m259[m[36m:[m        if [1;31mfactory_id[m is not None:
[35mapp/services/product_service.py[m[36m:[m[32m260[m[36m:[m            base_q = base_q.filter(Product.[1;31mfactory_id[m == [1;31mfactory_id[m)
[35mapp/services/product_service.py[m[36m:[m[32m293[m[36m:[m        [1;31mfactory_id[m: int | None = None,
[35mapp/services/product_service.py[m[36m:[m[32m297[m[36m:[m        if [1;31mfactory_id[m is not None:
[35mapp/services/product_service.py[m[36m:[m[32m298[m[36m:[m            q = q.filter(Product.[1;31mfactory_id[m == [1;31mfactory_id[m)
[35mapp/services/product_service.py[m[36m:[m[32m307[m[36m:[m    def production_stats(self, [1;31mfactory_id[m: int | None = None):
[35mapp/services/product_service.py[m[36m:[m[32m311[m[36m:[m        if [1;31mfactory_id[m is not None:
[35mapp/services/product_service.py[m[36m:[m[32m312[m[36m:[m            q_all = q_all.filter(Product.[1;31mfactory_id[m == [1;31mfactory_id[m)
[35mapp/services/product_service.py[m[36m:[m[32m313[m[36m:[m            q_today = q_today.filter(Product.[1;31mfactory_id[m == [1;31mfactory_id[m)
[35mapp/services/product_service.py[m[36m:[m[32m323[m[36m:[m    def stock_value_sell_totals(self, [1;31mfactory_id[m: int | None = None):
[35mapp/services/product_service.py[m[36m:[m[32m326[m[36m:[m        if [1;31mfactory_id[m is not None:
[35mapp/services/product_service.py[m[36m:[m[32m327[m[36m:[m            q = q.filter(Product.[1;31mfactory_id[m == [1;31mfactory_id[m)
[35mapp/services/product_service.py[m[36m:[m[32m342[m[36m:[m    def stock_profit_totals(self, [1;31mfactory_id[m: int | None = None):
[35mapp/services/product_service.py[m[36m:[m[32m345[m[36m:[m        if [1;31mfactory_id[m is not None:
[35mapp/services/product_service.py[m[36m:[m[32m346[m[36m:[m            q = q.filter(Product.[1;31mfactory_id[m == [1;31mfactory_id[m)
[35mapp/services/product_service.py[m[36m:[m[32m361[m[36m:[m    def get_low_stock_products(self, [1;31mfactory_id[m: int | None = None):
[35mapp/services/product_service.py[m[36m:[m[32m364[m[36m:[m        if [1;31mfactory_id[m is not None:
[35mapp/services/product_service.py[m[36m:[m[32m365[m[36m:[m            q = q.filter(Product.[1;31mfactory_id[m == [1;31mfactory_id[m)
[35mapp/services/product_service.py[m[36m:[m[32m373[m[36m:[m    def _get_or_create_shop_stock(self, product_id: int, [1;31mfactory_id[m: int) -> ShopStock:
[35mapp/services/product_service.py[m[36m:[m[32m379[m[36m:[m                Product.[1;31mfactory_id[m == [1;31mfactory_id[m,
[35mapp/services/product_service.py[m[36m:[m[32m389[m[36m:[m    def transfer_to_shop(self, [1;31mfactory_id[m: int, product_id: int, quantity: int):
[35mapp/services/product_service.py[m[36m:[m[32m393[m[36m:[m            .filter_by(id=product_id, [1;31mfactory_id[m=[1;31mfactory_id[m)
[35mapp/services/product_service.py[m[36m:[m[32m403[m[36m:[m        shop_stock = self._get_or_create_shop_stock(product_id, [1;31mfactory_id[m)
[35mapp/services/product_service.py[m[36m:[m[32m413[m[36m:[m        [1;31mfactory_id[m: int | None = None,
[35mapp/services/product_service.py[m[36m:[m[32m420[m[36m:[m        if [1;31mfactory_id[m is not None:
[35mapp/services/product_service.py[m[36m:[m[32m421[m[36m:[m            q = q.filter(Product.[1;31mfactory_id[m == [1;31mfactory_id[m)
[35mapp/services/product_service.py[m[36m:[m[32m446[m[36m:[m    def shop_stock_totals(self, [1;31mfactory_id[m: int | None = None):
[35mapp/services/product_service.py[m[36m:[m[32m449[m[36m:[m        if [1;31mfactory_id[m is not None:
[35mapp/services/product_service.py[m[36m:[m[32m450[m[36m:[m            q = q.filter(Product.[1;31mfactory_id[m == [1;31mfactory_id[m)
[35mapp/services/product_service.py[m[36m:[m[32m466[m[36m:[m    def weekly_shop_report(self, [1;31mfactory_id[m: int | None = None):
[35mapp/services/product_service.py[m[36m:[m[32m475[m[36m:[m        if [1;31mfactory_id[m is not None:
[35mapp/services/product_service.py[m[36m:[m[32m476[m[36m:[m            shop_q = shop_q.filter(Product.[1;31mfactory_id[m == [1;31mfactory_id[m)
[35mapp/services/product_service.py[m[36m:[m[32m522[m[36m:[m    def get_monthly_report(self, [1;31mfactory_id[m: int | None = None):
[35mapp/services/product_service.py[m[36m:[m[32m527[m[36m:[m        if [1;31mfactory_id[m is not None:
[35mapp/services/product_service.py[m[36m:[m[32m528[m[36m:[m            base = base.filter(Product.[1;31mfactory_id[m == [1;31mfactory_id[m)
[35mapp/services/product_service.py[m[36m:[m[32m546[m[36m:[m                *( [Product.[1;31mfactory_id[m == [1;31mfactory_id[m] if [1;31mfactory_id[m is not None else [] ),
[35mapp/services/product_service.py[m[36m:[m[32m563[m[36m:[m                *( [Product.[1;31mfactory_id[m == [1;31mfactory_id[m] if [1;31mfactory_id[m is not None else [] ),
[35mapp/services/product_service.py[m[36m:[m[32m583[m[36m:[m    def get_manager_financial_report(self, [1;31mfactory_id[m: int | None = None):
[35mapp/services/product_service.py[m[36m:[m[32m588[m[36m:[m        if [1;31mfactory_id[m is not None:
[35mapp/services/product_service.py[m[36m:[m[32m589[m[36m:[m            q_products = q_products.filter(Product.[1;31mfactory_id[m == [1;31mfactory_id[m)
[35mapp/services/product_service.py[m[36m:[m[32m603[m[36m:[m        if [1;31mfactory_id[m is not None:
[35mapp/services/product_service.py[m[36m:[m[32m604[m[36m:[m            q_shop = q_shop.filter(Product.[1;31mfactory_id[m == [1;31mfactory_id[m)
[35mapp/services/product_service.py[m[36m:[m[32m619[m[36m:[m        if [1;31mfactory_id[m is not None:
[35mapp/services/product_service.py[m[36m:[m[32m620[m[36m:[m            q_fabrics = q_fabrics.filter(Fabric.[1;31mfactory_id[m == [1;31mfactory_id[m)
[35mapp/services/product_service.py[m[36m:[m[32m631[m[36m:[m        totals = self.sales_totals([1;31mfactory_id[m=[1;31mfactory_id[m)
[35mapp/services/product_service.py[m[36m:[m[32m643[m[36m:[m        if [1;31mfactory_id[m is not None:
[35mapp/services/product_service.py[m[36m:[m[32m644[m[36m:[m            month_q = month_q.filter(Product.[1;31mfactory_id[m == [1;31mfactory_id[m)
[35mapp/services/product_service.py[m[36m:[m[32m655[m[36m:[m        stock_profit_uzs, stock_profit_usd = self.stock_profit_totals([1;31mfactory_id[m=[1;31mfactory_id[m)
[35mapp/services/product_service.py[m[36m:[m[32m659[m[36m:[m        if [1;31mfactory_id[m is not None:
[35mapp/services/product_service.py[m[36m:[m[32m660[m[36m:[m            all_q = all_q.filter(Product.[1;31mfactory_id[m == [1;31mfactory_id[m)
[35mapp/services/product_service.py[m[36m:[m[32m726[m[36m:[m        [1;31mfactory_id[m: int | None = None,
[35mapp/services/product_service.py[m[36m:[m[32m735[m[36m:[m        if [1;31mfactory_id[m is not None:
[35mapp/services/product_service.py[m[36m:[m[32m736[m[36m:[m            q = q.filter(Product.[1;31mfactory_id[m == [1;31mfactory_id[m)
[35mapp/services/shop_service.py[m[36m:[m[32m32[m[36m:[m        [1;31mfactory_id[m: Optional[int] = None,
[35mapp/services/shop_service.py[m[36m:[m[32m36[m[36m:[m        if [1;31mfactory_id[m is not None:
[35mapp/services/shop_service.py[m[36m:[m[32m37[m[36m:[m            query = query.filter(Product.[1;31mfactory_id[m == [1;31mfactory_id[m)
[35mapp/services/shop_service.py[m[36m:[m[32m81[m[36m:[m        [1;31mfactory_id[m: Optional[int] = None,
[35mapp/services/shop_service.py[m[36m:[m[32m87[m[36m:[m        if [1;31mfactory_id[m is not None:
[35mapp/services/shop_service.py[m[36m:[m[32m88[m[36m:[m            product_query = product_query.filter(Product.[1;31mfactory_id[m == [1;31mfactory_id[m)
[35mapp/services/shop_service.py[m[36m:[m[32m108[m[36m:[m        effective_[1;31mfactory_id[m = [1;31mfactory_id[m or product.[1;31mfactory_id[m
[35mapp/services/shop_service.py[m[36m:[m[32m111[m[36m:[m            [1;31mfactory_id[m=effective_[1;31mfactory_id[m,
[35mapp/services/shop_service.py[m[36m:[m[32m122[m[36m:[m            [1;31mfactory_id[m=effective_[1;31mfactory_id[m,
[35mapp/services/shop_service.py[m[36m:[m[32m141[m[36m:[m        [1;31mfactory_id[m: Optional[int] = None,
[35mapp/services/shop_service.py[m[36m:[m[32m148[m[36m:[m        if [1;31mfactory_id[m is not None:
[35mapp/services/shop_service.py[m[36m:[m[32m149[m[36m:[m            query = query.filter(Product.[1;31mfactory_id[m == [1;31mfactory_id[m)
[35mapp/services/shop_service.py[m[36m:[m[32m165[m[36m:[m        [1;31mfactory_id[m: Optional[int] = None,
[35mapp/services/shop_service.py[m[36m:[m[32m171[m[36m:[m        if [1;31mfactory_id[m is not None:
[35mapp/services/shop_service.py[m[36m:[m[32m172[m[36m:[m            product_query = product_query.filter(Product.[1;31mfactory_id[m == [1;31mfactory_id[m)
[35mapp/services/shop_service.py[m[36m:[m[32m183[m[36m:[m        if [1;31mfactory_id[m is not None:
[35mapp/services/shop_service.py[m[36m:[m[32m184[m[36m:[m            stock_query = stock_query.filter(Product.[1;31mfactory_id[m == [1;31mfactory_id[m)
[35mapp/services/shop_service.py[m[36m:[m[32m188[m[36m:[m        effective_[1;31mfactory_id[m = [1;31mfactory_id[m or product.[1;31mfactory_id[m
[35mapp/services/shop_service.py[m[36m:[m[32m211[m[36m:[m                [1;31mfactory_id[m=effective_[1;31mfactory_id[m,
[35mapp/services/shop_service.py[m[36m:[m[32m223[m[36m:[m                [1;31mfactory_id[m=effective_[1;31mfactory_id[m,
[35mapp/services/shop_service.py[m[36m:[m[32m263[m[36m:[m                [1;31mfactory_id[m=effective_[1;31mfactory_id[m,
[35mapp/services/shop_service.py[m[36m:[m[32m275[m[36m:[m                [1;31mfactory_id[m=effective_[1;31mfactory_id[m,
[35mapp/services/shop_service.py[m[36m:[m[32m290[m[36m:[m            [1;31mfactory_id[m=[1;31mfactory_id[m,
[35mapp/services/shop_service.py[m[36m:[m[32m307[m[36m:[m            [1;31mfactory_id[m=effective_[1;31mfactory_id[m,
[35mapp/services/shop_service.py[m[36m:[m[32m326[m[36m:[m                    [1;31mfactory_id[m=effective_[1;31mfactory_id[m,
[35mapp/services/shop_service.py[m[36m:[m[32m352[m[36m:[m        [1;31mfactory_id[m: Optional[int] = None,
[35mapp/services/shop_service.py[m[36m:[m[32m360[m[36m:[m        if [1;31mfactory_id[m is None:
[35mapp/services/shop_service.py[m[36m:[m[32m361[m[36m:[m            raise ValueError("[1;31mfactory_id[m is required for XLSX export")
[35mapp/services/shop_service.py[m[36m:[m[32m366[m[36m:[m        stock_data = self.list_items(q=q, sort=sort, [1;31mfactory_id[m=[1;31mfactory_id[m)
[35mapp/services/shop_service.py[m[36m:[m[32m375[m[36m:[m            .filter(Product.[1;31mfactory_id[m == [1;31mfactory_id[m)
