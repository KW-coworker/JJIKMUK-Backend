import ast,hashlib,json,re,unittest
from catalog_schema_inspection import CHILD,PARENT,SOURCE,SOURCE_SHA,document
from run import safe_report

class SchemaInspectionTest(unittest.TestCase):
    def describe(self,expected,actual):
        definitions=[n for n in ast.parse(CHILD).body if isinstance(n,ast.FunctionDef) and n.name in ('need','describe')]
        scope={'hashlib':hashlib,'json':json,'re':re}
        exec(compile(ast.Module(body=definitions,type_ignores=[]),'metadata-functions','exec'),scope)
        return scope['describe'](expected,actual)

    def test_exact_column_differences_are_reported_without_rows(self):
        result=self.describe({'barcode':'varchar(255)','required':'double','image_role':'varchar(32)'},
                             {'barcode':'varchar(255)','extra':'bigint unsigned'})
        self.assertEqual(result['counts']['extra_columns'],1)
        self.assertEqual(result['counts']['missing_required_columns'],1)
        self.assertIn('EXTRA_EXTRA',result['codes'])
        self.assertIn('ACTUAL_EXTRA__BIGINT_UNSIGNED',result['codes'])
        self.assertIn('MISSING_REQUIRED',result['codes'])
        self.assertNotIn('MISSING_IMAGE_ROLE',result['codes'])
        self.assertEqual(result['counts']['product_rows_read'],0)
        safe_report(json.dumps(result))

    def test_unsafe_schema_text_is_rejected(self):
        for actual in ({'private value':'text'},{'column':'secret://url'}):
            with self.assertRaises(ValueError):self.describe({},actual)

    def test_type_difference_and_equal_schema(self):
        self.assertIn('TYPE_DIFF_VALUE',self.describe({'value':'double'},{'value':'bigint'})['codes'])
        self.assertTrue(self.describe({'barcode':'varchar(255)'},{'barcode':'varchar(255)'})['checks']['same_compared_schema'])

    def test_fixed_programs_compile_and_select_metadata_only(self):
        compile('SOURCE='+repr(SOURCE)+'\n'+CHILD,'child','exec')
        compile('SOURCE='+repr(SOURCE)+'\nSOURCE_SHA='+repr(SOURCE_SHA)+'\nCHILD='+repr(CHILD)+'\n'+PARENT,'parent','exec')
        calls=[n.args[0].value for n in ast.walk(ast.parse(CHILD)) if isinstance(n,ast.Call) and
               isinstance(n.func,ast.Attribute) and n.func.attr=='execute' and n.args and isinstance(n.args[0],ast.Constant)]
        self.assertTrue(all(s.startswith(('SELECT ','SET SESSION ','START TRANSACTION ')) for s in calls))
        self.assertFalse(any('FROM products' in s or 'FROM `products`' in s for s in calls))
        self.assertIn('start_new_session=True',PARENT)
        self.assertIn('os.killpg',PARENT)
        self.assertLess(len(json.dumps(document())),60000)

if __name__=='__main__':unittest.main()
