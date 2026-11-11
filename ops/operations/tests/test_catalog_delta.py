import unittest
from catalog_delta import changes, identity, source_values, IMAGE_META


class DeltaTests(unittest.TestCase):
    columns = [('barcode','varchar(255)'),('product_id','bigint'),('product_name','text'),
               ('allergy_evidence_level','varchar(32)'),('allergy_data_confidence','double'),
               ('nutrition_basis_raw','varchar(255)'),('image_url','varchar(2048)'),
               *[(name,'varchar(255)') for name in IMAGE_META]]

    def row(self):
        return dict(barcode='fixture',product_id=42,product_name='sample',
                    allergy_evidence_level='UNKNOWN',allergy_data_confidence=None,
                    nutrition_basis_raw='100g',image_url='https://example.invalid/reference.png',
                    image_role='CATEGORY_REFERENCE',image_display_notice='Reference image',
                    image_asset_sha256='a'*64,image_assignment_run='fixture')

    def source(self,row):
        return dict(barcode=row['barcode'],product_id=row['product_id'],
                    identity_hash=identity(row,self.columns),values=source_values(row))

    def test_owner_supplied_quality_changes_do_not_reject_same_product(self):
        new=self.row();old=dict(new,allergy_evidence_level='INGREDIENT_DERIVED',allergy_data_confidence=.7)
        actual=changes(old,self.source(new),self.columns)
        self.assertEqual(actual,{'allergy_evidence_level':'UNKNOWN','allergy_data_confidence':None})

    def test_empty_image_copies_role_notice_and_audit_together(self):
        new=self.row();old=dict(new,image_url=None,nutrition_basis_raw=None)
        actual=changes(old,self.source(new),self.columns)
        self.assertEqual(set(actual),{'nutrition_basis_raw','image_url',*IMAGE_META})

    def test_existing_image_and_metadata_are_preserved(self):
        new=self.row();old=dict(new,image_url='https://example.invalid/existing.png',image_role=None)
        self.assertEqual(changes(old,self.source(new),self.columns),{})

    def test_changed_identity_id_or_existing_basis_stops(self):
        new=self.row()
        for change in ({'product_id':99},{'product_name':'different'},{'nutrition_basis_raw':'1 serving'}):
            with self.assertRaises(ValueError):changes(dict(new,**change),self.source(new),self.columns)

    def test_missing_source_values_never_erase_existing_basis(self):
        new=dict(self.row(),nutrition_basis_raw=None);old=dict(new,nutrition_basis_raw='1 serving')
        self.assertEqual(changes(old,self.source(new),self.columns),{})

    def test_invalid_source_quality_and_image_metadata_are_rejected(self):
        for change in ({'allergy_data_confidence':float('nan')},{'allergy_data_confidence':2},
                       {'allergy_evidence_level':'TRUST_ME'},{'image_asset_sha256':'bad'},
                       {'image_url':'http://example.invalid/a'},{'image_display_notice':''}):
            with self.assertRaises(ValueError):source_values(dict(self.row(),**change))

    def test_roleless_image_is_not_mislabeled_when_source_legacy_image_missing_on_host(self):
        new=dict(self.row(),image_role=None);old=dict(new,image_url=None)
        with self.assertRaisesRegex(ValueError,'NO_SOURCE_ROLE'):
            changes(old,self.source(new),self.columns)

    def test_historical_http_url_is_preserved_but_never_newly_assigned(self):
        new=dict(self.row(),image_role=None,image_url='http://example.invalid/legacy.jpg')
        self.assertEqual(changes(new,self.source(new),self.columns),{})
        with self.assertRaisesRegex(ValueError,'NO_SOURCE_ROLE'):
            changes(dict(new,image_url=None),self.source(new),self.columns)

    def test_source_evidence_and_supplied_confidence_are_preserved(self):
        values = source_values(dict(self.row(), allergy_evidence_level='SOURCE_INGREDIENTS', allergy_data_confidence=.42))
        self.assertEqual(values['allergy_evidence_level'], 'SOURCE_INGREDIENTS')
        self.assertEqual(values['allergy_data_confidence'], .42)


if __name__=='__main__':unittest.main()
